import html
import os
from pathlib import Path
from statistics import median
import tempfile

import pymupdf


class PdfDocument:
    def __init__(self, path):
        self.source = Path(path).resolve(strict=True)
        self.document = pymupdf.open(self.source)
        try:
            if self.document.needs_pass or self.document.is_encrypted:
                raise ValueError('Encrypted PDFs are not supported.')
            if self.document.is_pdf:
                if self.document.is_repaired:
                    raise ValueError('The PDF is damaged and required repair.')
                if self.document.permissions != -1 and not (self.document.permissions & pymupdf.PDF_PERM_MODIFY):
                    raise ValueError('This PDF does not permit editing.')
                for page in self.document:
                    if any(w.field_type == pymupdf.PDF_WIDGET_TYPE_SIGNATURE and w.field_value for w in (page.widgets() or ())):
                        raise ValueError('PDFs with signature fields are not supported.')
                for xref in range(1, self.document.xref_length()):
                    if self.document.xref_get_key(xref, 'Type') == ('name', '/Sig'):
                        raise ValueError('Digitally signed PDFs are not supported.')
            else:
                if self.source.suffix.lower() not in ('.jpg', '.jpeg', '.png'):
                    raise ValueError('Only PDF, JPG and PNG files are supported.')
                data = self.document.convert_to_pdf()
                self.document.close()
                self.document = pymupdf.open('pdf', data)
            if not self.document.page_count:
                raise ValueError('The document has no pages.')
        except Exception:
            self.document.close()
            raise
        self._undo = []
        self._redo = []
        self._last_replace = None
        self._revision = object()
        self._saved_revision = self._revision

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
        self.document.close()
        self.document = pymupdf.open('pdf', data[10:] if empty else data)
        if empty:
            self.document.delete_page(0)

    def _change_pages(self, page_index, operation, *, allow_empty=False):
        if not isinstance(page_index, int) or not (0 <= page_index < self.page_count or allow_empty and self.page_count == 0 and page_index == -1):
            raise ValueError('Select a valid page.')
        before = self._snapshot()
        revision = self._revision
        try:
            operation()
        except Exception:
            self._restore(before)
            raise
        self._undo.append((before, revision))
        self._redo.clear()
        self._revision = object()
        self._last_replace = None

    def delete_page(self, page_index):
        self._change_pages(page_index, lambda: self.document.delete_page(page_index))

    def duplicate_page(self, page_index):
        def duplicate():
            with pymupdf.open('pdf', self.document.tobytes()) as source:
                self.document.insert_pdf(source, from_page=page_index, to_page=page_index,
                                         start_at=page_index + 1, annots=True, widgets=True)
        self._change_pages(page_index, duplicate)

    def insert_pdf(self, path, after_page_index):
        with pymupdf.open(path) as check:
            if not check.is_pdf:
                raise ValueError('Only PDF files can be inserted.')
        source = PdfDocument(path)
        try:
            self._change_pages(after_page_index, lambda: self.document.insert_pdf(
                source.document, start_at=after_page_index + 1, annots=True, widgets=True), allow_empty=True)
        finally:
            source.close()

    def spans(self, page_index):
        result = []
        for block in self.document[page_index].get_text('dict')['blocks']:
            for line in block.get('lines', ()):
                for span in line['spans']:
                    if span['text'].strip():
                        result.append({key: span[key] for key in ('text', 'bbox', 'size', 'color', 'origin')})
        return result

    def characters(self, page_index):
        result = []
        line_id = 0
        for block in self.document[page_index].get_text('rawdict')['blocks']:
            for line in block.get('lines', ()):
                for span in line['spans']:
                    for char in span['chars']:
                        result.append({'text': char['c'], 'bbox': char['bbox'],
                                       'origin': char['origin'], 'line': line_id})
                line_id += 1
        return result

    def delete_characters(self, page_index, characters):
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
        rectangles = []
        for char in selected:
            rect = pymupdf.Rect(char['bbox'])
            if rect.is_empty or rect.is_infinite or not page_rect.contains(rect):
                raise ValueError('Select a valid area inside the page.')
            if any(rect.intersects(image) for image in images):
                raise ValueError('Text je nad obrázkom. Zakryte ho ikonou obdĺžnika a pridajte nový text ikonou T.')
            redaction = pymupdf.Rect(rect.x0 + rect.width * 0.45, rect.y0 + rect.height * 0.25,
                                     rect.x1 - rect.width * 0.45, rect.y1 - rect.height * 0.25)
            if any(redaction.intersects(pymupdf.Rect(other['bbox'])) for other in remaining):
                raise ValueError('The selected area overlaps neighboring text.')
            rectangles.append(redaction)
        before = self.document.tobytes()
        revision = self._revision
        try:
            for rect in rectangles:
                page.add_redact_annot(rect, fill=False)
            page.apply_redactions(images=0, graphics=0, text=0)
        except Exception:
            self.document.close()
            self.document = pymupdf.open('pdf', before)
            raise
        self._undo.append((before, revision))
        self._redo.clear()
        self._revision = object()
        self._last_replace = None

    def render(self, page_index, scale=1.5, clip=None):
        page = self.document[page_index]
        matrix = pymupdf.Matrix(scale, scale)
        if not any(w.field_type == pymupdf.PDF_WIDGET_TYPE_SIGNATURE and not w.field_value for w in (page.widgets() or ())):
            return page.get_pixmap(matrix=matrix, clip=clip, alpha=False)
        with pymupdf.open('pdf', self.document.tobytes()) as preview:
            page = preview[page_index]
            for widget in list(page.widgets() or ()):
                if widget.field_type == pymupdf.PDF_WIDGET_TYPE_SIGNATURE and not widget.field_value:
                    page.delete_widget(widget)
            return page.get_pixmap(matrix=matrix, clip=clip, alpha=False)

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
        color = tuple(median(channel) / 255 for channel in zip(*samples)) if samples else (1, 1, 1)
        before = self.document.tobytes()
        revision = self._revision
        try:
            page.add_redact_annot(rect, fill=color)
            page.apply_redactions(images=2, graphics=0, text=0)
            if destination is not None:
                with pymupdf.open('pdf', before) as source:
                    source[page_index].set_rotation(0)
                    image = source[page_index].get_pixmap(matrix=pymupdf.Matrix(3, 3), clip=rect, alpha=False, annots=False)
                    page.insert_image(target, stream=image.tobytes('png'), keep_proportion=False, overlay=True)
        except Exception:
            self.document.close()
            self.document = pymupdf.open('pdf', before)
            raise
        self._undo.append((before, revision))
        self._redo.clear()
        self._revision = object()
        self._last_replace = None
        return color

    def replace_text(self, page_index, bbox, text, fontsize=11, color=0, background=True, *, update_previous=False, insert_only=False):
        if update_previous:
            if (not self._undo or not self._last_replace
                    or self._last_replace[0] is not self._undo[-1]
                    or self._last_replace[1:] != (page_index, tuple(bbox), insert_only)):
                raise ValueError('There is no previous edit to update.')
            current = self.document.tobytes()
            revision = self._revision
            original, original_revision = self._undo[-1]
            self.document.close()
            self.document = pymupdf.open('pdf', original)
            self._revision = original_revision
            try:
                self.replace_text(page_index, bbox, text, fontsize, color, background, insert_only=insert_only)
            except Exception:
                self.document.close()
                self.document = pymupdf.open('pdf', current)
                self._revision = revision
                raise
            del self._undo[-2]
            return
        page = self.document[page_index]
        rect = pymupdf.Rect(bbox)
        if rect.is_empty or rect.is_infinite or not (page.rect * page.derotation_matrix).contains(rect):
            raise ValueError('Select a valid area inside the page.')
        if not isinstance(text, str) or fontsize <= 0:
            raise ValueError('Enter valid text and font size.')
        redaction = pymupdf.Rect(rect)
        native = None if insert_only else next((span for block in page.get_text('dict')['blocks'] for line in block.get('lines', ()) for span in line['spans'] if pymupdf.Rect(span['bbox']) == rect), None)
        if native:
            if any(rect.intersects(pymupdf.Rect(image['bbox'])) for image in page.get_image_info()):
                raise ValueError('Text je nad obrázkom. Zakryte ho ikonou obdĺžnika a pridajte nový text ikonou T.')
            redaction.y0 += rect.height * 0.25
            redaction.y1 -= rect.height * 0.25
        allowed = rect + (-0.05, -0.05, 0.05, 0.05)
        if not insert_only:
            for block in page.get_text('rawdict')['blocks']:
                for line in block.get('lines', ()):
                    for span in line['spans']:
                        for char in span['chars']:
                            char_rect = pymupdf.Rect(char['bbox'])
                            if redaction.intersects(char_rect) and not allowed.contains(char_rect):
                                raise ValueError('The selected area overlaps neighboring text.')
        if not insert_only and any(annot.type[0] == pymupdf.PDF_ANNOT_REDACT for annot in (page.annots() or ())):
            raise ValueError('Strana obsahuje existujúce redakcie. Pred úpravou ich odstráňte alebo použite inú kópiu.')
        before = self.document.tobytes()
        revision = self._revision
        try:
            if not insert_only:
                page.add_redact_annot(redaction, fill=(1, 1, 1) if background else False)
                page.apply_redactions(images=2, graphics=0, text=0)
            if text:
                rgb = '#%06x' % (color & 0xffffff)
                content = html.escape(text).replace('\n', '<br>')
                # shortcut: replacement uses Segoe UI rather than the original font, use font matching when exact typography is required.
                if native and '\n' not in text:
                    suffix = 'z' if native['flags'] & 18 == 18 else ('b' if native['flags'] & 16 else ('i' if native['flags'] & 2 else ''))
                    fontfile = str(Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts' / f'segoeui{suffix}.ttf')
                    font = pymupdf.Font(fontfile=fontfile)
                    width = font.text_length(text, fontsize=fontsize)
                    fitted = min(fontsize, native['size'], fontsize * rect.width / width) if width else min(fontsize, native['size'])
                    if fitted < fontsize * 0.7:
                        raise ValueError('The replacement text does not fit in the selected area.')
                    page.insert_font(fontname='editor' + (suffix or 'regular'), fontfile=fontfile)
                    page.insert_text(native['origin'], text, fontsize=fitted, fontname='editor' + (suffix or 'regular'), color=tuple(int(rgb[i:i+2], 16) / 255 for i in (1, 3, 5)))
                else:
                    spare, _ = page.insert_htmlbox(rect, content, css=f'body, p {{ margin: 0; padding: 0; line-height: 1; }} * {{ font-family: sans-serif; font-size: {fontsize}pt; color: {rgb}; }}', scale_low=0.7)
                    if spare < 0:
                        raise ValueError('The replacement text does not fit in the selected area.')
        except Exception:
            self.document.close()
            self.document = pymupdf.open('pdf', before)
            raise
        self._undo.append((before, revision))
        self._redo.clear()
        self._revision = object()
        self._last_replace = (self._undo[-1], page_index, tuple(rect), insert_only)

    def undo(self):
        if not self._undo:
            return False
        self._redo.append((self._snapshot(), self._revision))
        self._last_replace = None
        data, self._revision = self._undo.pop()
        self._restore(data)
        return True

    def redo(self):
        if not self._redo:
            return False
        self._undo.append((self._snapshot(), self._revision))
        self._last_replace = None
        data, self._revision = self._redo.pop()
        self._restore(data)
        return True

    def save_copy(self, path):
        if not self.page_count:
            raise ValueError('The document has no pages.')
        target = Path(path).resolve()
        if target == self.source or (target.exists() and os.path.samefile(target, self.source)):
            raise ValueError('The original file cannot be overwritten.')
        if target.exists():
            raise FileExistsError('Choose a new output file; existing files cannot be overwritten.')
        fd, temp = tempfile.mkstemp(prefix='.pdf-editor-', suffix='.pdf', dir=target.parent)
        os.close(fd)
        try:
            self.document.save(temp, garbage=3, deflate=True)
            with pymupdf.open(temp) as check:
                if check.is_repaired or check.page_count != self.page_count:
                    raise ValueError('The saved PDF could not be verified.')
                for page in check:
                    page.get_text()
            if os.name == 'nt':
                os.rename(temp, target)
            else:
                os.link(temp, target)
        finally:
            if os.path.exists(temp):
                os.unlink(temp)
        self._saved_revision = self._revision

    def close(self):
        self.document.close()
