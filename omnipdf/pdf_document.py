import html
import os
from dataclasses import dataclass
from contextlib import nullcontext
from itertools import groupby
from operator import itemgetter
from pathlib import Path
from statistics import median
import tempfile
from unicodedata import bidirectional, normalize

import pymupdf


TEXT_DICT = pymupdf.TEXTFLAGS_DICT & ~pymupdf.TEXT_PRESERVE_IMAGES
TEXT_CHARS = pymupdf.TEXTFLAGS_RAWDICT & ~pymupdf.TEXT_PRESERVE_IMAGES


def character_lines(characters):
    for _, group in groupby(characters, key=itemgetter('line')):
        line = list(group)
        box = pymupdf.Rect(line[0]['bbox'])
        for char in line[1:]:
            box.include_rect(char['bbox'])
        yield box, line


@dataclass(eq=False, slots=True)
class PageVersion:
    ocr: list | None = None
    needs_ocr: bool | None = None
    ocr_error: str | None = None


class SignedPdfError(ValueError):
    pass


class PdfDocument:
    HISTORY_LIMIT_BYTES = 128 * 1024 * 1024

    def __init__(self, path, *, allow_signed=False):
        self.source = Path(path).resolve(strict=True)
        self._source_stamp = self._file_stamp(self.source)
        self.searchable_source = False
        self.document = pymupdf.open(self.source)
        try:
            if self.document.needs_pass or self.document.is_encrypted:
                raise ValueError('Encrypted PDFs are not supported.')
            if self.document.is_pdf:
                if self.document.permissions != -1 and not (self.document.permissions & pymupdf.PDF_PERM_MODIFY):
                    raise ValueError('This PDF does not permit editing.')
                if not allow_signed:
                    for page in self.document:
                        if any(self._signed_widget(w) for w in (page.widgets() or ())):
                            raise SignedPdfError('PDFs with signature fields are not supported.')
                    for xref in range(1, self.document.xref_length()):
                        if self.document.xref_get_key(xref, 'Type') == ('name', '/Sig'):
                            raise SignedPdfError('Digitally signed PDFs are not supported.')
            else:
                if self.source.suffix.lower() not in ('.jpg', '.jpeg', '.png'):
                    raise ValueError('Only PDF, JPG and PNG files are supported.')
                data = self.document.convert_to_pdf()
                self.document.close()
                self.document = pymupdf.open('pdf', data)
            if not self.document.page_count:
                raise ValueError('The document has no pages.')
            self.recovered = self.document.is_repaired
            if self.recovered:
                self._verify_recovery()
        except Exception:
            self.document.close()
            raise
        self._undo = []
        self._redo = []
        self._last_replace = None
        self._revision = object()
        self._saved_revision = self._revision
        self.page_versions = [PageVersion() for _ in self.document]

    def _verify_recovery(self):
        count = self.page_count
        try:
            self._restore(self._snapshot())
            if self.document.is_repaired or count != self.page_count:
                raise ValueError('The recovered page count or PDF structure is invalid.')
            for page in self.document:
                page.get_displaylist()
        except Exception as exc:
            raise ValueError('The PDF could not be recovered.') from exc

    @property
    def dirty(self):
        return self._revision is not self._saved_revision

    @property
    def page_count(self):
        return self.document.page_count

    @property
    def can_undo(self):
        return bool(self._undo)

    @property
    def can_redo(self):
        return bool(self._redo)

    def _snapshot(self):
        if self.page_count:
            return self.document.tobytes()
        self.document.new_page()
        try:
            return b'empty-pdf:' + self.document.tobytes()
        finally:
            self.document.delete_page(0)

    def _restore(self, data):
        empty = data.startswith(b'empty-pdf:')
        restored = pymupdf.open('pdf', data[10:] if empty else data)
        self.document.close()
        self.document = restored
        if empty:
            self.document.delete_page(0)

    def _capture(self):
        return self._snapshot(), self._revision, self.page_versions.copy()

    def _restore_state(self, state):
        data, self._revision, versions = state
        self._restore(data)
        self.page_versions = versions.copy()

    def _record(self, before, page_index=None):
        if page_index is not None:
            self.page_versions[page_index] = PageVersion()
        self._undo.append(before)
        self._redo.clear()
        self._trim_history(self._undo)
        self._revision = object()
        self._last_replace = None

    def _trim_history(self, latest):
        total = sum(len(state[0]) for history in (self._undo, self._redo) for state in history)
        # Keep the most recent step even if one document exceeds the byte budget.
        while total > self.HISTORY_LIMIT_BYTES and len(self._undo) + len(self._redo) > 1:
            history = self._undo if self._undo and (latest is self._redo or len(self._undo) > 1) else self._redo
            total -= len(history.pop(0)[0])

    def _change_pages(self, page_index, operation, *, allow_empty=False):
        if not isinstance(page_index, int) or not (0 <= page_index < self.page_count or allow_empty and self.page_count == 0 and page_index == -1):
            raise ValueError('Select a valid page.')
        before = self._capture()
        versions = {self.document.page_xref(index): version for index, version in enumerate(self.page_versions)}
        try:
            operation()
        except Exception:
            self._restore_state(before)
            raise
        self.page_versions = [versions.get(self.document.page_xref(index)) or PageVersion()
                              for index in range(self.page_count)]
        self._record(before)

    def delete_page(self, page_index):
        self.delete_pages([page_index])

    def _selected_pages(self, indices):
        indices = list(indices)
        if not indices or not all(isinstance(i, int) and 0 <= i < self.page_count for i in indices):
            raise ValueError('Select a valid page.')
        return sorted(set(indices))

    def delete_pages(self, indices):
        indices = self._selected_pages(indices)
        self._change_pages(indices[0], lambda: self.document.delete_pages(indices))

    def rotate_pages(self, indices, angle):
        indices = self._selected_pages(indices)
        if angle not in (-90, 90):
            raise ValueError('Page rotation must be 90 degrees clockwise or counterclockwise.')
        def rotate():
            for index in indices:
                page = self.document[index]
                page.set_rotation((page.rotation + angle) % 360)
        self._change_pages(indices[0], rotate)
        for index in indices:
            version = self.page_versions[index]
            self.page_versions[index] = PageVersion(ocr=version.ocr or None, needs_ocr=version.needs_ocr)

    def move_pages(self, indices, boundary):
        indices = self._selected_pages(indices)
        if not isinstance(boundary, int) or not 0 <= boundary <= self.page_count:
            raise ValueError('Select a valid page.')
        selected = set(indices)
        order = [index for index in range(self.page_count) if index not in selected]
        destination = boundary - sum(index < boundary for index in indices)
        order[destination:destination] = indices
        if order != list(range(self.page_count)):
            self._change_pages(indices[0], lambda: self.document.select(order))
        return destination

    def duplicate_page(self, page_index):
        def duplicate():
            links = self.document[page_index].get_links()
            destination = page_index + 1
            with pymupdf.open('pdf', self.document.tobytes()) as source:
                self.document.insert_pdf(source, from_page=page_index, to_page=page_index,
                                         start_at=destination, annots=True, widgets=True)
            page = self.document[destination]
            for link in links:
                target = link.get('page', -1)
                if (link['kind'] == pymupdf.LINK_GOTO and isinstance(target, int)
                        and 0 <= target < self.page_count - 1 and target != page_index):
                    # insert_pdf copies self-links and external links, while dropping links outside the copied range.
                    link.pop('xref', None)
                    link.pop('id', None)
                    link['page'] = target + (target >= destination)
                    page.insert_link(link)
        self._change_pages(page_index, duplicate)

    def move_page(self, source, destination):
        if not all(isinstance(i, int) and 0 <= i < self.page_count for i in (source, destination)):
            raise ValueError('Select a valid page.')
        if source == destination:
            return
        before = destination + (source < destination)
        self._change_pages(source, lambda: self.document.move_page(source, before if before < self.page_count else -1))

    def insert_pdf(self, path, after_page_index, *, allow_signed=False):
        with pymupdf.open(path) as check:
            if not check.is_pdf:
                raise ValueError('Only PDF files can be inserted.')
        source = PdfDocument(path, allow_signed=allow_signed)
        try:
            self._change_pages(after_page_index, lambda: self.document.insert_pdf(
                source.document, start_at=after_page_index + 1, annots=True, widgets=True), allow_empty=True)
        finally:
            source.close()

    def spans(self, page_index):
        return [{key: span[key] for key in ('text', 'bbox', 'size', 'color', 'origin')}
                for span in self._visible_spans(self.document[page_index])]

    @staticmethod
    def _visible_spans(page):
        for block in page.get_text('dict', flags=TEXT_DICT)['blocks']:
            for line in block.get('lines', ()):
                for span in line['spans']:
                    if span['text'].strip() and span.get('alpha', 255):
                        yield span

    def characters(self, page_index, clip=None, *, include_hidden=False):
        result = []
        line_id = 0
        for block in self.document[page_index].get_text('rawdict', clip=clip, flags=TEXT_CHARS)['blocks']:
            for line in block.get('lines', ()):
                for span in line['spans']:
                    if not include_hidden and not span.get('alpha', 255):
                        continue
                    for char in span['chars']:
                        result.append({'text': char['c'], 'bbox': char['bbox'],
                                       'origin': char['origin'], 'line': line_id, 'direction': line['dir'],
                                       'size': span['size'], 'color': span['color'], 'flags': span['flags']})
                line_id += 1
        return result

    def find_text(self, page_index, query):
        needle = ' '.join(normalize('NFKD', query).casefold().split())
        if not needle:
            return []
        page = self.document[page_index]
        blocks = page.get_text('rawdict', flags=pymupdf.TEXTFLAGS_SEARCH)['blocks']
        text, positions = [], []
        line_number = 0
        for block in blocks:
            for line in block.get('lines', ()):
                dx, dy = line['dir']
                for span in line['spans']:
                    for char in span['chars']:
                        x, y = char['origin']
                        # A dehyphenated line can still occupy multiple baselines on the page.
                        baseline = round(y * dx - x * dy, 1)
                        for unit in normalize('NFKD', char['c']).casefold():
                            if not unit.isspace():
                                text.append(unit)
                                positions.append(((line_number, baseline), char['bbox']))
                            elif text and text[-1] != ' ':
                                text.append(' ')
                                positions.append(None)
                if text and text[-1] != ' ':
                    text.append(' ')
                    positions.append(None)
                line_number += 1
        haystack = ''.join(text)
        hits = []
        start = haystack.find(needle)
        while start >= 0:
            end = start + len(needle)
            fragments = {}
            for position in positions[start:end]:
                if position is not None:
                    line, box = position
                    if line in fragments:
                        fragments[line].include_rect(pymupdf.Rect(box))
                    else:
                        fragments[line] = pymupdf.Rect(box)
            hits.append(tuple(tuple(rect) for rect in fragments.values()))
            start = haystack.find(needle, end)
        return hits

    def delete_characters(self, page_index, characters):
        self._replace_characters(page_index, characters, '', 11, 0, False)

    def _replace_characters(self, page_index, characters, text, fontsize, color, background):
        page = self.document[page_index]
        remaining = self.characters(page_index)
        selected = []
        for char in characters:
            if char not in remaining:
                raise ValueError('The selected text is no longer available.')
            remaining.remove(char)
            selected.append(char)
        if not selected:
            raise ValueError('Select text to delete.')
        if any(annot.type[0] == pymupdf.PDF_ANNOT_REDACT for annot in (page.annots() or ())):
            raise ValueError('Strana obsahuje existujúce redakcie. Pred úpravou ich odstráňte alebo použite inú kópiu.')
        page_rect = page.rect * page.derotation_matrix
        images = [pymupdf.Rect(image['bbox']) for image in page.get_image_info()]
        neighbors = [pymupdf.Rect(char['bbox']) for char in remaining]
        rectangles = []
        for char in selected:
            rect = pymupdf.Rect(char['bbox'])
            if rect.is_empty or rect.is_infinite or not page_rect.contains(rect):
                raise ValueError('Select a valid area inside the page.')
            if any(rect.intersects(image) for image in images):
                raise ValueError('Text je nad obrázkom. Zakryte ho ikonou obdĺžnika a pridajte nový text ikonou T.')
            redaction = pymupdf.Rect(rect.x0 + rect.width * 0.45, rect.y0 + rect.height * 0.25,
                                     rect.x1 - rect.width * 0.45, rect.y1 - rect.height * 0.25)
            if any(redaction.intersects(other) for other in neighbors):
                raise ValueError('The selected area overlaps neighboring text.')
            rectangles.append(redaction)
        lines = list(character_lines(selected)) if text or background else []
        replacements = text.split('\n') if text else []
        if len(replacements) > len(lines):
            raise ValueError('The replacement text does not fit in the selected area.')
        if background and any(box.intersects(other) for box, _ in lines for other in neighbors):
            raise ValueError('The selected area overlaps neighboring text.')
        spans = list(self._visible_spans(page)) if replacements else []
        whole_spans = {tuple(span['bbox']) for span in spans}
        before = self._capture()
        try:
            for rect in rectangles:
                page.add_redact_annot(rect, fill=False)
            page.apply_redactions(images=0, graphics=0, text=0)
            if background:
                for box, _ in lines:
                    page.draw_rect(box, color=None, fill=(1, 1, 1))
            for (box, line), replacement in zip(lines, replacements):
                if replacement:
                    rotation = self._rotation(line[0]['direction'])
                    strip = self._text_strip(box, rotation)
                    if any(strip.intersects(other) for other in neighbors):
                        raise ValueError('The selected area overlaps neighboring text.')
                    align_right = (rotation == 0 and tuple(box) in whole_spans
                                   and self._is_right_aligned(box, spans))
                    self._insert_replacement(page, box, replacement, fontsize, color, line[0], rotation,
                                             align_right=align_right)
        except Exception:
            self._restore_state(before)
            raise
        self._record(before, page_index)

    def render(self, page_index, scale=1.5, clip=None):
        page = self.document[page_index]
        matrix = pymupdf.Matrix(scale, scale)
        if not any(w.field_type == pymupdf.PDF_WIDGET_TYPE_SIGNATURE and not self._signed_widget(w) for w in (page.widgets() or ())):
            return page.get_pixmap(matrix=matrix, clip=clip, alpha=False)
        with pymupdf.open('pdf', self.document.tobytes()) as preview:
            page = preview[page_index]
            for widget in list(page.widgets() or ()):
                if widget.field_type == pymupdf.PDF_WIDGET_TYPE_SIGNATURE and not self._signed_widget(widget, preview):
                    page.delete_widget(widget)
            return page.get_pixmap(matrix=matrix, clip=clip, alpha=False)

    def _signed_widget(self, widget, document=None):
        if widget.field_type != pymupdf.PDF_WIDGET_TYPE_SIGNATURE:
            return False
        document = document or self.document
        xref = widget.xref
        visited = set()
        while xref and xref not in visited:
            visited.add(xref)
            if document.xref_get_key(xref, 'V')[0] != 'null':
                return True
            kind, value = document.xref_get_key(xref, 'Parent')
            xref = int(value.split()[0]) if kind == 'xref' else None
        return bool(widget.field_value)

    @staticmethod
    def _sample_background(page, rect):
        scale = 1.5
        clip = (rect + (-4, -4, 4, 4)) * page.rotation_matrix
        pix = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), clip=clip, alpha=False, annots=False)
        samples = []
        for offset in (1.5, 3):
            for i in range(21):
                x = rect.x0 + rect.width * i / 20
                y = rect.y0 + rect.height * i / 20
                for point in ((x, rect.y0 - offset), (x, rect.y1 + offset),
                              (rect.x0 - offset, y), (rect.x1 + offset, y)):
                    p = pymupdf.Point(point) * page.rotation_matrix * pymupdf.Matrix(scale, scale)
                    px, py = int(p.x) - pix.x, int(p.y) - pix.y
                    if 0 <= px < pix.width and 0 <= py < pix.height:
                        samples.append(pix.pixel(px, py)[:3])
        # shortcut: nonuniform backgrounds get a flat color; use inpainting for photo-like areas.
        return tuple(median(channel) / 255 for channel in zip(*samples)) if samples else (1, 1, 1)

    def cover_region(self, page_index, bbox, destination=None):
        page = self.document[page_index]
        rect = pymupdf.Rect(bbox)
        if rect.is_empty or rect.is_infinite or not (page.rect * page.derotation_matrix).contains(rect):
            raise ValueError('Select a valid area inside the page.')
        if destination is not None:
            target = pymupdf.Rect(destination)
            if target.is_empty or target.is_infinite or not (page.rect * page.derotation_matrix).contains(target):
                raise ValueError('Select a valid area inside the page.')
        if any(annot.type[0] == pymupdf.PDF_ANNOT_REDACT for annot in (page.annots() or ())):
            raise ValueError('Strana obsahuje existujúce redakcie. Pred úpravou ich odstráňte alebo použite inú kópiu.')
        color = self._sample_background(page, rect)
        before = self._capture()
        try:
            page.add_redact_annot(rect, fill=color)
            page.apply_redactions(images=2, graphics=0, text=0)
            if destination is not None:
                with pymupdf.open('pdf', before[0]) as source:
                    self._insert_region(page, source, page_index, rect, target)
        except Exception:
            self._restore_state(before)
            raise
        self._record(before, page_index)
        return color

    def _insert_region(self, page, source, page_index, rect, target):
        source_page = source[page_index]
        source_page.set_rotation(0)
        rotation = page.rotation
        page.set_rotation(0)
        if any(rect.intersects(pymupdf.Rect(span['bbox'])) for span in self._visible_spans(source_page)):
            # A display clip alone would import text and images from outside the selection.
            source_page.clip_to_rect(rect)
            self._clear_image_pixels_outside(source_page, rect)
            page.draw_rect(target, color=None, fill=(1, 1, 1))
            page.show_pdf_page(target, source, page_index, keep_proportion=False, clip=rect)
        else:
            image = source_page.get_pixmap(matrix=pymupdf.Matrix(3, 3), clip=rect, alpha=False, annots=False)
            page.insert_image(target, stream=image.tobytes('png'), keep_proportion=False, overlay=True)
        page.set_rotation(rotation)

    @staticmethod
    def _clear_image_pixels_outside(page, rect):
        bounds = pymupdf.Rect(rect)
        for image in page.get_image_info():
            bounds.include_rect(image['bbox'])
        if bounds == rect:
            return
        strips = (
            pymupdf.Rect(bounds.x0, bounds.y0, rect.x0, bounds.y1),
            pymupdf.Rect(rect.x1, bounds.y0, bounds.x1, bounds.y1),
            pymupdf.Rect(rect.x0, bounds.y0, rect.x1, rect.y0),
            pymupdf.Rect(rect.x0, rect.y1, rect.x1, bounds.y1),
        )
        for strip in strips:
            if not strip.is_empty:
                page.add_redact_annot(strip, fill=False)
        page.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_PIXELS,
                              graphics=pymupdf.PDF_REDACT_LINE_ART_NONE, text=pymupdf.PDF_REDACT_TEXT_NONE)

    def transform_region(self, page_index, bbox, destination, baseline):
        current = self._capture()
        self._restore(baseline)
        try:
            if destination is not None and pymupdf.Rect(bbox) == pymupdf.Rect(destination):
                self._record(current, page_index)
            else:
                self.cover_region(page_index, bbox, destination)
                self._undo[-1] = current
                self._trim_history(self._undo)
        except Exception:
            self._restore_state(current)
            raise

    @staticmethod
    def _rotation(direction):
        rotation = {(1, 0): 0, (0, -1): 90, (-1, 0): 180, (0, 1): 270}.get(
            tuple(round(value, 6) for value in direction))
        if rotation is None:
            raise ValueError('Text at this angle cannot be edited directly.')
        return rotation

    @staticmethod
    def _text_strip(rect, rotation):
        if rotation in (90, 270):
            inset = rect.width * 0.25
            return rect + (inset, 0, -inset, 0)
        inset = rect.height * 0.25
        return rect + (0, inset, 0, -inset)

    @staticmethod
    def _is_right_aligned(rect, spans):
        center_y = (rect.y0 + rect.y1) / 2
        tolerance = min(2, max(0.75, rect.height * 0.12))
        left_matches = right_matches = 0
        for span in spans:
            other = pymupdf.Rect(span['bbox'])
            distance = abs((other.y0 + other.y1) / 2 - center_y)
            if rect.height * 0.45 < distance <= rect.height * 8:
                left_matches += abs(other.x0 - rect.x0) <= tolerance
                right_matches += abs(other.x1 - rect.x1) <= tolerance
        return right_matches > left_matches

    def replace_text(self, page_index, bbox, text, fontsize=11, color=0, background=False, *,
                     update_previous=False, insert_only=False, characters=None):
        characters = tuple(characters) if characters is not None else None
        selection = (page_index, tuple(bbox), insert_only, characters)
        if update_previous:
            if (not self._undo or not self._last_replace
                    or self._last_replace[0] is not self._undo[-1]
                    or self._last_replace[1:] != selection):
                raise ValueError('There is no previous edit to update.')
            current = self._capture()
            original = self._undo.pop()
            try:
                self._restore_state(original)
                self.replace_text(page_index, bbox, text, fontsize, color, background,
                                  insert_only=insert_only, characters=characters)
            except Exception:
                self._restore_state(current)
                self._undo.append(original)
                raise
            return
        page = self.document[page_index]
        rect = pymupdf.Rect(bbox)
        if rect.is_empty or rect.is_infinite or not (page.rect * page.derotation_matrix).contains(rect):
            raise ValueError('Select a valid area inside the page.')
        if not isinstance(text, str) or fontsize <= 0:
            raise ValueError('Enter valid text and font size.')
        if characters is not None:
            self._replace_characters(page_index, characters, text, fontsize, color, background)
            self._last_replace = (self._undo[-1], *selection)
            return
        redaction = pymupdf.Rect(rect)
        lines = () if insert_only else tuple(
            line for block in page.get_text('dict', flags=TEXT_DICT)['blocks'] for line in block.get('lines', ()))
        native, direction = next(
            ((span, line['dir']) for line in lines for span in line['spans']
             if span.get('alpha', 255) and pymupdf.Rect(span['bbox']) == rect), (None, None))
        over_image = not insert_only and any(
            rect.intersects(pymupdf.Rect(image['bbox'])) for image in page.get_image_info())
        rotation = 0
        align_right = False
        if native:
            if over_image:
                raise ValueError('Text je nad obrázkom. Zakryte ho ikonou obdĺžnika a pridajte nový text ikonou T.')
            rotation = self._rotation(direction)
            redaction = self._text_strip(rect, rotation)
            align_right = rotation == 0 and self._is_right_aligned(
                rect, (span for line in lines if line['dir'] == direction for span in line['spans']
                       if span['text'].strip() and span.get('alpha', 255)))
        elif not insert_only:
            ocr = self.page_versions[page_index].ocr or ()
            if any(pymupdf.Rect(span['bbox']) == rect for span in ocr):
                align_right = self._is_right_aligned(rect, ocr)
        allowed = rect + (-0.05, -0.05, 0.05, 0.05)
        if not insert_only:
            for block in page.get_text('rawdict', flags=TEXT_CHARS)['blocks']:
                for line in block.get('lines', ()):
                    for span in line['spans']:
                        for char in span['chars']:
                            char_rect = pymupdf.Rect(char['bbox'])
                            if redaction.intersects(char_rect) and not allowed.contains(char_rect):
                                raise ValueError('The selected area overlaps neighboring text.')
        if not insert_only and any(annot.type[0] == pymupdf.PDF_ANNOT_REDACT for annot in (page.annots() or ())):
            raise ValueError('Strana obsahuje existujúce redakcie. Pred úpravou ich odstráňte alebo použite inú kópiu.')
        before = self._capture()
        try:
            if not insert_only:
                fill = (1, 1, 1) if background else False
                if over_image and not background:
                    fill = self._sample_background(page, redaction)
                page.add_redact_annot(redaction, fill=fill)
                page.apply_redactions(images=2 if over_image else 0, graphics=0, text=0)
                if native and any(char['text'].strip() and redaction.intersects(pymupdf.Rect(char['bbox']))
                                  for char in self.characters(page_index, clip=allowed, include_hidden=True)):
                    raise ValueError('The original text could not be removed safely.')
            if text:
                self._insert_replacement(page, rect, text, fontsize, color, native, rotation,
                                         align_right=align_right)
        except Exception:
            self._restore_state(before)
            raise
        self._record(before, page_index)
        self._last_replace = (self._undo[-1], *selection)

    @staticmethod
    def _insert_replacement(page, rect, text, fontsize, color, native, rotation, *, align_right=False):
        font = None
        fallback = False
        if native and '\n' not in text:
            # shortcut: replacement uses Segoe UI rather than the original font, use font matching when exact typography is required.
            suffix = 'z' if native['flags'] & 18 == 18 else ('b' if native['flags'] & 16 else ('i' if native['flags'] & 2 else ''))
            fontfile = str(Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts' / f'segoeui{suffix}.ttf')
            font = pymupdf.Font(fontfile=fontfile)
            fallback = any(not font.has_glyph(ord(char), fallback=False) for char in text)
        rgb = '#%06x' % (color & 0xffffff)
        if font is not None and not fallback:
            width = font.text_length(text, fontsize=fontsize)
            available = rect.height if rotation in (90, 270) else rect.width
            fitted = min(fontsize, native['size'], fontsize * available / width) if width else min(fontsize, native['size'])
            if fitted < fontsize * 0.7:
                raise ValueError('The replacement text does not fit in the selected area.')
            origin = native['origin']
            if align_right:
                origin = (rect.x1 - font.text_length(text, fontsize=fitted), origin[1])
            page.insert_font(fontname='editor' + (suffix or 'regular'), fontfile=fontfile)
            inserted = page.insert_text(origin, text, fontsize=fitted, rotate=rotation,
                                        fontname='editor' + (suffix or 'regular'), color=tuple(int(rgb[i:i+2], 16) / 255 for i in (1, 3, 5)))
            if inserted < 1:
                raise ValueError('The replacement text does not fit in the selected area.')
        else:
            content = html.escape(text).replace('\n', '<br>')
            alignment = ' text-align: right;' if align_right else ''
            spare, _ = page.insert_htmlbox(rect, content, css=f'body, p {{ margin: 0; padding: 0; line-height: 1;{alignment} }} * {{ font-family: sans-serif; font-size: {fontsize}pt; color: {rgb}; }}', scale_low=0.7, rotate=rotation)
            if spare < 0:
                raise ValueError('The replacement text does not fit in the selected area.')
            if fallback and normalize('NFC', ''.join(text.split())) != normalize('NFC', ''.join(page.get_textbox(rect).split())):
                raise ValueError('Some characters in the replacement text cannot be rendered.')

    def undo(self):
        if not self._undo:
            return False
        self._redo.append(self._capture())
        self._last_replace = None
        self._restore_state(self._undo.pop())
        self._trim_history(self._redo)
        return True

    def redo(self):
        if not self._redo:
            return False
        self._undo.append(self._capture())
        self._last_replace = None
        self._restore_state(self._redo.pop())
        self._trim_history(self._undo)
        return True

    @staticmethod
    def _file_stamp(path):
        stat = path.stat()
        return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns

    def _add_searchable_text(self, document):
        font = pymupdf.Font('helv')
        for index, version in enumerate(self.page_versions):
            if not version.ocr:
                continue
            page = document[index]
            rotation = page.rotation
            # TextWriter places text in unrotated page coordinates.
            page.set_rotation(0)
            try:
                self._write_searchable_page(page, version.ocr, font)
            finally:
                page.set_rotation(rotation)

    @staticmethod
    def _write_searchable_page(page, lines, font):
        bounds = page.rect
        before = page.get_textpage()
        writers = {}
        added = []
        for line in lines:
            rect = pymupdf.Rect(line['bbox']) & bounds
            content = ' '.join(line['text'].split())
            if rect.is_empty or not content:
                continue
            expected = normalize('NFC', ''.join(content.split()))
            if expected in normalize('NFC', ''.join(page.get_textbox(rect, textpage=before).split())):
                continue
            angle = line.get('rotation', 0)
            if any(bidirectional(char) in ('R', 'AL', 'AN') for char in content):
                css = f'body,p {{margin:0;padding:0;line-height:1}} * {{font-size:{line["size"]}pt}}'
                spare, _ = page.insert_htmlbox(rect, html.escape(content), css=css, scale_low=0,
                                               opacity=0, rotate=angle)
                if spare < 0:
                    raise ValueError('Some recognized text could not be saved as searchable text.')
            else:
                if angle not in writers:
                    writers[angle] = pymupdf.TextWriter(bounds)
                box = rect * pymupdf.Matrix(angle)
                padding = min(0.15, box.width / 4, box.height / 4)
                width = font.text_length(content, fontsize=1)
                size = min(line['size'], (box.width - 2 * padding) / max(width, 1),
                           (box.height - 2 * padding) / (font.ascender - font.descender))
                writers[angle].append((box.x0 + padding, box.y0 + padding + font.ascender * size),
                                      content, font=font, fontsize=size)
            added.append((rect, expected))
        for angle, writer in writers.items():
            writer.write_text(page, morph=(pymupdf.Point(0, 0), pymupdf.Matrix(angle)), opacity=0, render_mode=3)
        after = page.get_textpage()
        for rect, expected in added:
            if expected not in normalize('NFC', ''.join(page.get_textbox(rect, textpage=after).split())):
                raise ValueError('Some recognized text could not be saved as searchable text.')

    def save_copy(self, path, *, replace_source=False, searchable=False):
        if not self.page_count:
            raise ValueError('The document has no pages.')
        target = Path(path).resolve()
        same_path = target == self.source
        replacing = replace_source and same_path and self.source.suffix.casefold() == '.pdf'
        searchable = searchable or (replacing and self.searchable_source)
        if not replacing and (same_path or (target.exists() and self.source.exists() and os.path.samefile(target, self.source))):
            raise ValueError('The original file cannot be overwritten.')
        if target.exists() and not replacing:
            raise FileExistsError('Choose a new output file; existing files cannot be overwritten.')
        fd, temp = tempfile.mkstemp(prefix='.pdf-editor-', suffix='.pdf', dir=target.parent)
        os.close(fd)
        try:
            with (pymupdf.open('pdf', self._snapshot()) if searchable else nullcontext(self.document)) as output:
                if searchable:
                    self._add_searchable_text(output)
                output.save(temp, garbage=3, deflate=True)
            with pymupdf.open(temp) as check:
                if check.is_repaired or check.page_count != self.page_count:
                    raise ValueError('The saved PDF could not be verified.')
                for page in check:
                    page.get_text()
            if replacing:
                # MuPDF can hold the original open on Windows. Keep the live document in memory before the swap.
                if self.document.name:
                    self._restore(self._snapshot())
                with open(temp, 'r+b') as staged:
                    os.fsync(staged.fileno())
                if not target.exists() or self._file_stamp(target) != self._source_stamp:
                    raise ValueError('The original PDF changed on disk. Save a copy or reopen the file.')
                os.replace(temp, target)
                self._source_stamp = self._file_stamp(target)
                self.searchable_source = searchable
            elif os.name == 'nt':
                os.rename(temp, target)
            else:
                os.link(temp, target)
        finally:
            if os.path.exists(temp):
                os.unlink(temp)
        self._saved_revision = self._revision

    def close(self):
        self.document.close()
