import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pymupdf

from pdf_document import PdfDocument


class PdfDocumentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / 'source.pdf'
        doc = pymupdf.open()
        page = doc.new_page(width=400, height=250)
        page.insert_text((30, 60), 'Old text', fontsize=12)
        page.insert_text((230, 60), 'Neighbor', fontsize=12)
        page.draw_line((20, 80), (350, 80))
        doc.new_page().insert_text((40, 60), 'Second page')
        doc.save(self.source)
        doc.close()
        self.pdf = PdfDocument(self.source)

    def tearDown(self):
        self.pdf.close()
        self.temp.cleanup()

    def test_recovers_a_pdf_with_a_missing_xref_stream_size(self):
        broken = self.root / 'recoverable.pdf'
        with pymupdf.open(self.source) as original:
            data = original.tobytes(use_objstms=1)
        self.assertEqual(data.count(b'/Size '), 1)
        damaged = data.replace(b'/Size ', b'/Lost ')
        broken.write_bytes(damaged)
        with pymupdf.open(broken) as check:
            self.assertTrue(check.is_repaired)
        recovered = PdfDocument(broken)
        try:
            self.assertTrue(recovered.recovered)
            self.assertFalse(recovered.dirty)
            self.assertFalse(recovered.document.is_repaired)
            self.assertEqual(recovered.page_count, 2)
            self.assertEqual(recovered.render(0).samples, self.pdf.render(0).samples)
            self.assertIn('Second page', recovered.document[1].get_text())
            output = self.root / 'recovered.pdf'
            recovered.save_copy(output)
            with pymupdf.open(output) as saved:
                self.assertFalse(saved.is_repaired)
                self.assertEqual(saved.page_count, 2)
            self.assertEqual(broken.read_bytes(), damaged)
        finally:
            recovered.close()

    def test_confirmed_replace_preserves_undo_and_checks_external_changes(self):
        span = self.pdf.spans(0)[0]
        self.pdf.replace_text(0, span['bbox'], 'New text', fontsize=span['size'])
        before = self.source.read_bytes()
        with patch('pdf_document.os.replace', side_effect=PermissionError('busy')):
            with self.assertRaisesRegex(PermissionError, 'busy'):
                self.pdf.save_copy(self.source, replace_source=True)
        self.assertEqual(self.source.read_bytes(), before)
        self.assertTrue(self.pdf.dirty)
        self.assertEqual(list(self.root.glob('.pdf-editor-*')), [])
        self.pdf.save_copy(self.source, replace_source=True)
        self.assertFalse(self.pdf.dirty)
        with pymupdf.open(self.source) as saved:
            self.assertIn('New text', saved[0].get_text())
        self.assertTrue(self.pdf.undo())
        stamp = self.source.stat()
        os.utime(self.source, ns=(stamp.st_atime_ns, stamp.st_mtime_ns + 2_000_000_000))
        with self.assertRaisesRegex(ValueError, 'changed on disk'):
            self.pdf.save_copy(self.source, replace_source=True)
        with pymupdf.open(self.source) as saved:
            self.assertIn('New text', saved[0].get_text())

    def test_searchable_save_keeps_pixels_and_preserves_ocr_on_resave(self):
        before = self.pdf.render(0).samples
        self.pdf.page_versions[0].ocr = [{'text': 'Žltý dokument 12345', 'bbox': (35, 122, 225, 145), 'size': 13}]
        self.pdf.save_copy(self.source, replace_source=True, searchable=True)
        for _ in range(2):
            with pymupdf.open(self.source) as saved:
                self.assertIn('Žltý dokument 12345', saved[0].get_text())
                self.assertEqual(before, saved[0].get_pixmap(matrix=pymupdf.Matrix(1.5, 1.5)).samples)
            self.pdf.save_copy(self.source, replace_source=True)
        reopened = PdfDocument(self.source)
        try:
            text = self.pdf.page_versions[0].ocr[0]['text']
            self.assertNotIn(text, [span['text'] for span in reopened.spans(0)])
            reopened.page_versions[0].ocr = self.pdf.page_versions[0].ocr
            output = self.root / 'searchable-again.pdf'
            reopened.save_copy(output, searchable=True)
            with pymupdf.open(output) as saved:
                self.assertEqual(saved[0].get_text().count(text), 1)
        finally:
            reopened.close()

    def test_batch_page_changes_preserve_order_and_each_undo_as_one_step(self):
        self.pdf.insert_pdf(self.source, 1)
        versions = self.pdf.page_versions.copy()
        self.assertEqual(self.pdf.move_pages([0, 2], 4), 2)
        self.assertEqual(self.pdf.page_versions, [versions[i] for i in (1, 3, 0, 2)])
        self.pdf.page_versions[2].ocr = []
        self.pdf.rotate_pages([2, 3], 90)
        self.assertEqual([page.rotation for page in self.pdf.document], [0, 0, 90, 90])
        self.assertIsNone(self.pdf.page_versions[2].ocr)
        self.pdf.delete_pages([1, 2])
        self.assertEqual(self.pdf.page_count, 2)
        self.assertTrue(self.pdf.undo())
        self.assertEqual([page.rotation for page in self.pdf.document], [0, 0, 90, 90])
        self.assertTrue(self.pdf.undo())
        self.assertEqual(self.pdf.page_versions, [versions[i] for i in (1, 3, 0, 2)])
        self.assertTrue(self.pdf.undo())
        self.assertEqual(self.pdf.page_versions, versions)

    def test_searchable_layer_preserves_page_rotation(self):
        self.pdf.rotate_pages([0], 90)
        self.pdf.page_versions[0].ocr = [{'text': 'Rotated scan 12345', 'bbox': (100, 100, 130, 235),
                                          'size': 12, 'rotation': 90}]
        before = self.pdf.render(0).samples
        output = self.root / 'rotated-searchable.pdf'
        self.pdf.save_copy(output, searchable=True)
        with pymupdf.open(output) as saved:
            self.assertEqual(saved[0].rotation, 90)
            self.assertIn('Rotated scan 12345', saved[0].get_text())
            self.assertEqual(before, saved[0].get_pixmap(matrix=pymupdf.Matrix(1.5, 1.5)).samples)

    def test_page_operations_preserve_content_and_history(self):
        source_bytes = self.source.read_bytes()
        page = self.pdf.document[0]
        page.add_text_annot((100, 100), 'Note')
        field = pymupdf.Widget()
        field.field_name = 'Name'
        field.field_type = pymupdf.PDF_WIDGET_TYPE_TEXT
        field.field_value = 'Alice'
        field.rect = pymupdf.Rect(100, 120, 200, 140)
        page.add_widget(field)
        self.pdf.duplicate_page(0)
        self.assertEqual(self.pdf.page_count, 3)
        self.assertIn('Old text', self.pdf.document[1].get_text())
        self.assertEqual(next(self.pdf.document[1].annots()).info['content'], 'Note')
        self.assertEqual(next(self.pdf.document[1].widgets()).field_value, 'Alice')
        self.assertTrue(self.pdf.dirty)
        duplicated = self.root / 'duplicated.pdf'
        self.pdf.save_copy(duplicated)
        with pymupdf.open(duplicated) as saved:
            self.assertEqual(next(saved[1].widgets()).field_value, 'Alice')
            self.assertEqual(next(saved[1].annots()).info['content'], 'Note')
        self.assertTrue(self.pdf.undo())
        self.assertEqual(self.pdf.page_count, 2)
        self.assertTrue(self.pdf.dirty)
        self.assertTrue(self.pdf.redo())
        self.assertFalse(self.pdf.dirty)
        self.pdf.delete_page(1)
        self.assertEqual(self.pdf.page_count, 2)
        self.assertIn('Second page', self.pdf.document[1].get_text())
        self.assertTrue(self.pdf.undo())
        self.assertEqual(self.pdf.page_count, 3)
        self.assertTrue(self.pdf.redo())
        output = self.root / 'pages.pdf'
        self.pdf.save_copy(output)
        with pymupdf.open(output) as saved:
            self.assertEqual(saved.page_count, 2)
            self.assertEqual(next(saved[0].widgets()).field_value, 'Alice')
            self.assertEqual(next(saved[0].annots()).info['content'], 'Note')
        self.assertEqual(self.source.read_bytes(), source_bytes)

    def test_insert_pdf_and_rejections(self):
        original = self.source.read_bytes()
        self.pdf.insert_pdf(self.source, 0)
        self.assertEqual(self.pdf.page_count, 4)
        self.assertIn('Old text', self.pdf.document[1].get_text())
        self.assertIn('Second page', self.pdf.document[2].get_text())
        self.assertIn('Second page', self.pdf.document[3].get_text())
        self.assertTrue(self.pdf.undo())
        self.assertFalse(self.pdf.dirty)
        self.assertTrue(self.pdf.redo())
        self.assertEqual(self.source.read_bytes(), original)
        for method in (self.pdf.delete_page, self.pdf.duplicate_page):
            for index in (-1, self.pdf.page_count):
                with self.assertRaises(ValueError):
                    method(index)
        with self.assertRaises(ValueError):
            self.pdf.insert_pdf(self.source, -1)
        with patch.object(pymupdf.Document, 'insert_pdf', side_effect=RuntimeError('failure')):
            with self.assertRaises(RuntimeError):
                self.pdf.duplicate_page(0)
        self.assertEqual(self.pdf.page_count, 4)
        self.assertTrue(self.pdf.undo())
        self.assertEqual(self.pdf.page_count, 2)
        self.pdf.delete_page(0)
        self.pdf.delete_page(0)
        self.assertEqual(self.pdf.page_count, 0)
        with self.assertRaises(ValueError):
            self.pdf.save_copy(self.root / 'empty.pdf')
        self.assertTrue(self.pdf.undo())
        self.assertEqual(self.pdf.page_count, 1)

    def test_insert_rejects_non_pdf_and_encrypted_pdf(self):
        image = self.root / 'image.png'
        pix = pymupdf.Pixmap(pymupdf.csRGB, (0, 0, 2, 2), False)
        pix.clear_with(255)
        pix.save(image)
        with self.assertRaises(ValueError):
            self.pdf.insert_pdf(image, 0)
        encrypted = self.root / 'encrypted-source.pdf'
        with pymupdf.open(self.source) as doc:
            doc.save(encrypted, encryption=pymupdf.PDF_ENCRYPT_AES_256,
                     owner_pw='owner', user_pw='secret')
        with self.assertRaises(ValueError):
            self.pdf.insert_pdf(encrypted, 0)
        self.assertEqual(self.pdf.page_count, 2)
        self.assertFalse(self.pdf.dirty)
        self.assertFalse(self.pdf.can_undo)

    def test_empty_document_history_preserves_metadata_and_failed_insert(self):
        self.pdf.document.set_metadata({'title': 'Kept title'})
        self.pdf.delete_page(1)
        self.pdf.delete_page(0)
        with patch.object(pymupdf.Document, 'insert_pdf', side_effect=RuntimeError('failure')):
            with self.assertRaises(RuntimeError):
                self.pdf.insert_pdf(self.source, -1)
        self.assertEqual(self.pdf.page_count, 0)
        self.assertEqual(self.pdf.document.metadata['title'], 'Kept title')
        self.pdf.insert_pdf(self.source, -1)
        self.assertEqual(self.pdf.page_count, 2)
        self.assertTrue(self.pdf.undo())
        self.assertEqual(self.pdf.page_count, 0)
        self.assertEqual(self.pdf.document.metadata['title'], 'Kept title')
        self.assertTrue(self.pdf.redo())
        self.assertEqual(self.pdf.page_count, 2)
        self.assertEqual(self.pdf.document.metadata['title'], 'Kept title')

    def test_replace_save_and_undo(self):
        self.pdf.replace_text(0, (25, 40, 180, 75), 'Žltý kôň', fontsize=12)
        self.assertNotIn('Old text', self.pdf.document[0].get_text())
        self.assertIn('Žltý kôň', self.pdf.document[0].get_text())
        self.assertIn('Neighbor', self.pdf.document[0].get_text())
        self.assertIn('Second page', self.pdf.document[1].get_text())
        self.assertTrue(self.pdf.document[0].get_drawings())
        self.assertTrue(self.pdf.dirty)
        output = self.root / 'copy.pdf'
        self.pdf.save_copy(output)
        self.assertFalse(self.pdf.dirty)
        self.assertTrue(self.pdf.undo())
        self.assertTrue(self.pdf.dirty)
        self.assertIn('Old text', self.pdf.document[0].get_text())
        self.assertFalse(self.pdf.undo())
        self.assertTrue(self.pdf.can_redo)
        self.assertTrue(self.pdf.redo())
        self.assertFalse(self.pdf.dirty)
        self.assertIn('Žltý kôň', self.pdf.document[0].get_text())
        self.assertFalse(self.pdf.redo())
        with pymupdf.open(output) as doc:
            self.assertIn('Žltý kôň', doc[0].get_text())
        with pymupdf.open(self.source) as doc:
            self.assertIn('Old text', doc[0].get_text())

    def test_failure_rolls_back_and_prevents_overwrite(self):
        with self.assertRaises(ValueError):
            self.pdf.replace_text(0, (25, 40, 100, 75), 'Too long ' * 100, fontsize=12)
        self.assertIn('Old text', self.pdf.document[0].get_text())
        self.assertFalse(self.pdf.dirty)
        self.assertFalse(self.pdf.can_undo)
        with self.assertRaises(ValueError):
            self.pdf.replace_text(0, (25, 40, 235, 75), 'Bad selection')
        with self.assertRaises(ValueError):
            self.pdf.save_copy(self.source)
        existing = self.root / 'existing.pdf'
        existing.write_bytes(b'unchanged')
        with self.assertRaises(FileExistsError):
            self.pdf.save_copy(existing)
        self.assertEqual(existing.read_bytes(), b'unchanged')

    def test_repeated_replacement_is_one_undo_and_failure_restores_last_edit(self):
        span = self.pdf.spans(0)[0]
        args = (0, span['bbox'])
        self.pdf.replace_text(*args, 'New', fontsize=12)
        self.pdf.replace_text(*args, '', fontsize=12, update_previous=True)
        self.assertNotIn('Old text', self.pdf.document[0].get_text())
        self.pdf.replace_text(*args, 'Newer', fontsize=12, update_previous=True)
        with self.assertRaises(ValueError):
            self.pdf.replace_text(*args, 'Too long ' * 100, fontsize=12, update_previous=True)
        self.assertIn('Newer', self.pdf.document[0].get_text())
        self.assertIn('Neighbor', self.pdf.document[0].get_text())
        output = self.root / 'updated.pdf'
        self.pdf.save_copy(output)
        self.assertFalse(self.pdf.dirty)
        self.pdf.replace_text(*args, 'Final', fontsize=12, update_previous=True)
        self.assertTrue(self.pdf.dirty)
        self.assertTrue(self.pdf.undo())
        self.assertTrue(self.pdf.dirty)
        self.assertIn('Old text', self.pdf.document[0].get_text())
        self.assertFalse(self.pdf.undo())
        self.assertTrue(self.pdf.redo())
        self.assertIn('Final', self.pdf.document[0].get_text())
        self.assertFalse(self.pdf.redo())
        with pymupdf.open(output) as saved:
            self.assertIn('Newer', saved[0].get_text())

    def test_redo_multiple_edits_and_branching(self):
        self.pdf.replace_text(0, (25, 40, 180, 75), 'New', fontsize=12)
        self.pdf.cover_region(0, (220, 40, 300, 75))
        self.assertNotIn('Neighbor', self.pdf.document[0].get_text())
        self.assertTrue(self.pdf.undo())
        self.assertIn('Neighbor', self.pdf.document[0].get_text())
        self.assertTrue(self.pdf.undo())
        self.assertTrue(self.pdf.redo())
        self.assertIn('New', self.pdf.document[0].get_text())
        self.assertTrue(self.pdf.redo())
        self.assertNotIn('Neighbor', self.pdf.document[0].get_text())
        self.assertTrue(self.pdf.undo())
        with self.assertRaises(ValueError):
            self.pdf.cover_region(0, (-1, -1, 0, 0))
        self.assertTrue(self.pdf.can_redo)
        self.pdf.delete_characters(0, self.pdf.characters(0)[:1])
        self.assertFalse(self.pdf.can_redo)

    def test_insert_text_preserves_content_and_groups_updates(self):
        args = (0, (25, 40, 180, 90))
        original_drawings = self.pdf.document[0].get_drawings()
        self.pdf.replace_text(*args, 'Žltý', insert_only=True)
        self.pdf.replace_text(*args, 'Nový', update_previous=True, insert_only=True)
        with self.assertRaises(ValueError):
            self.pdf.replace_text(*args, 'Too long ' * 1000, update_previous=True, insert_only=True)
        with self.assertRaises(ValueError):
            self.pdf.replace_text(*args, 'Wrong mode', update_previous=True)
        text = self.pdf.document[0].get_text()
        self.assertIn('Old text', text)
        self.assertIn('Nový', text)
        self.assertEqual(self.pdf.document[0].get_drawings(), original_drawings)
        self.assertTrue(self.pdf.undo())
        self.assertNotIn('Nový', self.pdf.document[0].get_text())
        self.assertIn('Old text', self.pdf.document[0].get_text())
        self.assertTrue(self.pdf.redo())
        self.assertIn('Nový', self.pdf.document[0].get_text())
        self.assertEqual(self.pdf.document[0].get_drawings(), original_drawings)
        with pymupdf.open(self.source) as source:
            self.assertNotIn('Nový', source[0].get_text())

    def test_blank_insert_update_removes_only_inserted_text(self):
        args = (0, (25, 40, 180, 90))
        self.pdf.replace_text(*args, 'Added', insert_only=True)
        self.pdf.replace_text(*args, '', update_previous=True, insert_only=True)
        self.assertNotIn('Added', self.pdf.document[0].get_text())
        self.assertIn('Old text', self.pdf.document[0].get_text())
        self.assertTrue(self.pdf.undo())
        self.assertTrue(self.pdf.redo())
        self.assertIn('Old text', self.pdf.document[0].get_text())
        self.assertNotIn('Added', self.pdf.document[0].get_text())

    def test_equal_length_span_with_overlapping_line_metrics(self):
        doc = pymupdf.open()
        page = doc.new_page()
        page.insert_text((30, 60), 'INVOICE12345', fontsize=12)
        page.insert_text((30, 73), 'Neighbor', fontsize=12)
        path = self.root / 'overlap.pdf'
        doc.save(path)
        doc.close()
        pdf = PdfDocument(path)
        try:
            span = pdf.spans(0)[0]
            pdf.replace_text(0, span['bbox'], 'INVOICE12346', fontsize=span['size'])
            text = pdf.document[0].get_text()
            self.assertIn('INVOICE12346', text)
            replacement = next(s for s in pdf.spans(0) if s['text'] == 'INVOICE12346')
            self.assertAlmostEqual(replacement['origin'][1], span['origin'][1], places=3)
            self.assertIn('Neighbor', text)
            self.assertNotIn('INVOICE12345', text)
        finally:
            pdf.close()

    def test_delete_partial_text_across_lines_is_one_undo(self):
        doc = pymupdf.open()
        page = doc.new_page()
        page.insert_text((30, 60), 'INVOICE12345', fontsize=12)
        page.insert_text((30, 73), 'Neighbor', fontsize=12)
        page.draw_line((20, 75), (300, 75))
        path = self.root / 'ranges.pdf'
        doc.save(path)
        doc.close()
        pdf = PdfDocument(path)
        try:
            chars = pdf.characters(0)
            self.assertEqual(''.join(c['text'] for c in chars), 'INVOICE12345Neighbor')
            self.assertEqual([c['line'] for c in chars], [0] * 12 + [1] * 8)
            pdf.delete_characters(0, chars[7:12] + chars[12:15])
            text = pdf.document[0].get_text()
            self.assertIn('INVOICE', text)
            self.assertIn('ghbor', text)
            self.assertNotIn('12345', text)
            self.assertTrue(pdf.document[0].get_drawings())
            output = self.root / 'ranges-copy.pdf'
            pdf.save_copy(output)
            with pymupdf.open(output) as saved:
                self.assertNotIn('12345', saved[0].get_text())
                self.assertIn('ghbor', saved[0].get_text())
            with pymupdf.open(path) as source:
                self.assertIn('INVOICE12345', source[0].get_text())
            self.assertTrue(pdf.undo())
            self.assertIn('INVOICE12345', pdf.document[0].get_text())
            self.assertIn('Neighbor', pdf.document[0].get_text())
            self.assertFalse(pdf.undo())
        finally:
            pdf.close()

    def test_delete_rejects_text_over_image_and_existing_redaction(self):
        pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 100, 100), False)
        pix.clear_with(0)
        path = self.root / 'image.pdf'
        doc = pymupdf.open()
        page = doc.new_page(width=100, height=100)
        page.insert_image(page.rect, pixmap=pix)
        page.insert_text((10, 40), 'OCR', fontsize=12)
        doc.save(path)
        doc.close()
        pdf = PdfDocument(path)
        try:
            with self.assertRaisesRegex(ValueError, 'Zakryte ho ikonou'):
                pdf.delete_characters(0, pdf.characters(0)[:1])
            pdf.document[0].add_redact_annot((1, 1, 5, 5))
            with self.assertRaisesRegex(ValueError, 'existujúce redakcie'):
                pdf.delete_characters(0, pdf.characters(0)[:1])
            self.assertIn('OCR', pdf.document[0].get_text())
            self.assertFalse(pdf.can_undo)
        finally:
            pdf.close()

    def test_delete_rejects_overlapping_unselected_character(self):
        doc = pymupdf.open()
        page = doc.new_page()
        page.insert_text((30, 60), 'A', fontsize=12)
        page.insert_text((30, 60), 'B', fontsize=12)
        path = self.root / 'overlapping.pdf'
        doc.save(path)
        doc.close()
        pdf = PdfDocument(path)
        try:
            with self.assertRaisesRegex(ValueError, 'overlaps neighboring text'):
                pdf.delete_characters(0, pdf.characters(0)[:1])
            self.assertIn('A', pdf.document[0].get_text())
            self.assertIn('B', pdf.document[0].get_text())
            self.assertFalse(pdf.can_undo)
        finally:
            pdf.close()

    def test_cover_region_samples_background_and_undoes(self):
        path = self.root / 'background.pdf'
        doc = pymupdf.open()
        page = doc.new_page(width=300, height=120)
        page.draw_rect(page.rect, color=None, fill=(0.8, 0.8, 0.8))
        page.insert_text((30, 60), 'Secret', fontsize=12)
        page.insert_text((150, 60), 'Neighbor', fontsize=12)
        doc.save(path)
        doc.close()
        pdf = PdfDocument(path)
        try:
            rect = pdf.spans(0)[0]['bbox']
            color = pdf.cover_region(0, rect)
            self.assertAlmostEqual(color[0], 0.8, delta=0.02)
            self.assertNotIn('Secret', pdf.document[0].get_text())
            self.assertIn('Neighbor', pdf.document[0].get_text())
            pixel = pdf.render(0, 1).pixel(32, 55)
            self.assertAlmostEqual(pixel[0], 204, delta=5)
            self.assertTrue(pdf.undo())
            self.assertIn('Secret', pdf.document[0].get_text())
            self.assertFalse(pdf.undo())
            with pymupdf.open(path) as source:
                self.assertIn('Secret', source[0].get_text())
        finally:
            pdf.close()

    def test_cover_region_white_and_existing_redaction(self):
        rect = self.pdf.spans(0)[0]['bbox']
        self.assertEqual(self.pdf.cover_region(0, rect), (1, 1, 1))
        self.assertNotIn('Old text', self.pdf.document[0].get_text())
        self.assertIn('Neighbor', self.pdf.document[0].get_text())
        self.pdf.undo()
        self.pdf.document[0].add_redact_annot((1, 1, 5, 5))
        with self.assertRaisesRegex(ValueError, 'existujúce redakcie'):
            self.pdf.cover_region(0, rect)
        self.assertIn('Old text', self.pdf.document[0].get_text())

    def test_unrelated_stroked_text_keeps_line_width(self):
        doc = pymupdf.open()
        page = doc.new_page()
        page.insert_text((30, 60), 'Old', fontsize=12)
        page.insert_text((30, 100), 'Stroked', fontsize=12, render_mode=2, border_width=0.03)
        path = self.root / 'stroked.pdf'
        doc.save(path)
        doc.close()
        pdf = PdfDocument(path)
        try:
            before = [span['linewidth'] for span in pdf.document[0].get_texttrace() if span['type'] == 1]
            span = next(s for s in pdf.spans(0) if s['text'] == 'Old')
            pdf.replace_text(0, span['bbox'], 'New', fontsize=span['size'])
            after = [span['linewidth'] for span in pdf.document[0].get_texttrace() if span['type'] == 1]
            self.assertTrue(before)
            self.assertEqual(before, after)
        finally:
            pdf.close()

    def test_text_over_scan_requires_manual_region(self):
        pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 100, 100), False)
        pix.clear_with(0)
        doc = pymupdf.open()
        page = doc.new_page(width=100, height=100)
        page.insert_image(page.rect, pixmap=pix)
        page.insert_text((10, 40), 'OCR', fontsize=12)
        path = self.root / 'ocr.pdf'
        doc.save(path)
        doc.close()
        pdf = PdfDocument(path)
        try:
            span = pdf.spans(0)[0]
            with self.assertRaisesRegex(ValueError, 'Zakryte ho ikonou'):
                pdf.replace_text(0, span['bbox'], 'New', fontsize=12)
            self.assertIn('OCR', pdf.document[0].get_text())
        finally:
            pdf.close()

    def test_existing_redaction_is_not_applied(self):
        page = self.pdf.document[0]
        page.add_redact_annot((225, 40, 310, 75))
        with self.assertRaisesRegex(ValueError, 'existujúce redakcie'):
            self.pdf.replace_text(0, (25, 40, 180, 75), 'New')
        self.assertIn('Old text', page.get_text())
        self.assertIn('Neighbor', page.get_text())
        self.assertFalse(self.pdf.dirty)

    def test_encrypted_pdf_is_rejected(self):
        path = self.root / 'encrypted.pdf'
        doc = pymupdf.open()
        doc.new_page()
        doc.save(path, encryption=pymupdf.PDF_ENCRYPT_AES_256,
                 owner_pw='owner', user_pw='password')
        doc.close()
        with self.assertRaisesRegex(ValueError, 'Encrypted'):
            PdfDocument(path)
        with self.assertRaisesRegex(ValueError, 'Encrypted'):
            PdfDocument(path, allow_signed=True)

    def test_empty_signature_field_is_accepted(self):
        path = self.root / 'unsigned.pdf'
        doc = pymupdf.open()
        page = doc.new_page()
        field = pymupdf.Widget()
        field.field_name = 'signature'
        field.field_type = pymupdf.PDF_WIDGET_TYPE_SIGNATURE
        field.rect = pymupdf.Rect(10, 10, 100, 40)
        page.add_widget(field)
        doc.save(path)
        doc.close()
        unsigned = PdfDocument(path)
        unsigned.close()

    def test_accepting_signatures_does_not_bypass_pdf_permissions(self):
        path = self.root / 'read-only.pdf'
        with pymupdf.open() as doc:
            doc.new_page()
            doc.save(path, encryption=pymupdf.PDF_ENCRYPT_AES_256, owner_pw='owner',
                     user_pw='', permissions=pymupdf.PDF_PERM_PRINT)
        with self.assertRaisesRegex(ValueError, 'permit editing'):
            PdfDocument(path, allow_signed=True)

    def test_signature_dictionary_is_rejected(self):
        path = self.root / 'signed.pdf'
        doc = pymupdf.open()
        doc.new_page()
        xref = doc.get_new_xref()
        doc.update_object(xref, '<< /Type /Sig /ByteRange [0 1 2 3] >>')
        doc.save(path)
        doc.close()
        with self.assertRaisesRegex(ValueError, 'signed'):
            PdfDocument(path)

    def test_rotated_page_uses_unrotated_coordinates(self):
        self.pdf.document[0].set_rotation(90)
        span = self.pdf.spans(0)[0]
        self.pdf.replace_text(0, span['bbox'], 'New', fontsize=span['size'])
        self.assertIn('New', self.pdf.document[0].get_text())
        self.assertNotIn('Old text', self.pdf.document[0].get_text())

    def test_vertical_text_replacement_erases_the_whole_span_and_keeps_direction(self):
        path = self.root / 'vertical.pdf'
        with pymupdf.open() as doc:
            for angle in (90, 270):
                page = doc.new_page(width=300, height=280)
                page.insert_text((95, 125), 'ABCDE', fontsize=12, rotate=angle)
                page.insert_text((180, 70), 'Neighbor', fontsize=12)
            doc.save(path)
        pdf = PdfDocument(path)
        try:
            for index, direction in enumerate(((0, -1), (0, 1))):
                span = pdf.spans(index)[0]
                pdf.replace_text(index, span['bbox'], 'XYZ', fontsize=span['size'])
                lines = {span['text']: tuple(line['dir']) for block in pdf.document[index].get_text('dict')['blocks']
                         for line in block.get('lines', ()) for span in line['spans']}
                self.assertEqual(lines, {'XYZ': direction, 'Neighbor': (1, 0)})
        finally:
            pdf.close()

    def test_replacement_uses_font_fallback_and_rejects_unrenderable_characters(self):
        original = self.pdf.spans(0)[0]
        with self.assertRaisesRegex(ValueError, 'cannot be rendered'):
            self.pdf.replace_text(0, original['bbox'], '\U0010ffff', fontsize=original['size'])
        self.assertIn(original['text'], self.pdf.document[0].get_text())
        self.assertFalse(self.pdf.can_undo)
        text = '中文測試'
        self.pdf.replace_text(0, original['bbox'], text, fontsize=original['size'])
        target = self.root / 'characters.pdf'
        self.pdf.save_copy(target)
        with pymupdf.open(target) as saved:
            self.assertIn(text, saved[0].get_text())
            self.assertNotIn(original['text'], saved[0].get_text())

    def test_duplicate_keeps_links_to_pages_before_and_after_it(self):
        source = self.root / 'links.pdf'
        with pymupdf.open() as doc:
            for label in ('Earlier', 'Page to duplicate', 'Later'):
                doc.new_page().insert_text((30, 60), label)
            page = doc[1]
            for target in range(3):
                y = 80 + 25 * target
                page.insert_link({'kind': pymupdf.LINK_GOTO, 'from': pymupdf.Rect(30, y, 110, y + 15), 'page': target})
            doc.save(source)
        pdf = PdfDocument(source)
        try:
            pdf.duplicate_page(1)
            target = self.root / 'copied-links.pdf'
            pdf.save_copy(target)
            with pymupdf.open(target) as saved:
                self.assertEqual(sorted(link['page'] for link in saved[1].get_links()), [0, 1, 3])
                self.assertEqual(sorted(link['page'] for link in saved[2].get_links()), [0, 2, 3])
        finally:
            pdf.close()

    def test_history_budget_keeps_latest_step_and_coalesces_large_edits(self):
        self.pdf.HISTORY_LIMIT_BYTES = len(self.pdf.document.tobytes()) * 3
        for _ in range(6):
            self.pdf.move_page(0, 1)
        self.assertGreater(len(self.pdf._undo), 1)
        self.assertLess(len(self.pdf._undo), 6)
        for operation in (self.pdf.undo, self.pdf.redo):
            self.assertTrue(operation())
            self.assertLessEqual(sum(len(state[0]) for stack in (self.pdf._undo, self.pdf._redo) for state in stack),
                                 self.pdf.HISTORY_LIMIT_BYTES)

        self.pdf.HISTORY_LIMIT_BYTES = 1
        span = self.pdf.spans(0)[0]
        self.pdf.replace_text(0, span['bbox'], 'New', fontsize=span['size'])
        self.pdf.replace_text(0, span['bbox'], 'Latest', fontsize=span['size'], update_previous=True)
        self.assertIn('Latest', self.pdf.document[0].get_text())
        self.assertEqual(len(self.pdf._undo), 1)
        self.assertTrue(self.pdf.undo())
        self.assertIn(span['text'], self.pdf.document[0].get_text())

    def test_native_text_cannot_grow_outside_its_row(self):
        span = self.pdf.spans(0)[0]
        with self.assertRaises(ValueError):
            self.pdf.replace_text(0, span['bbox'], 'I', fontsize=60)
        self.assertIn('Old text', self.pdf.document[0].get_text())
        self.assertFalse(self.pdf.dirty)

    def test_explicit_white_fill_removes_scan_pixels(self):
        # A black image simulates ink in a scanned document.
        pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 100, 100), False)
        pix.clear_with(0)
        path = self.root / 'scan.png'
        pix.save(path)
        scan = PdfDocument(path)
        try:
            scan.replace_text(0, (10, 10, 65, 40), 'A', fontsize=10, background=True)
            rendered = scan.render(0, 1)
            self.assertGreater(rendered.pixel(60, 30)[0], 240)
            self.assertLess(rendered.pixel(5, 5)[0], 10)
        finally:
            scan.close()

    def test_redo_restores_image_cover(self):
        pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 20, 20), False)
        pix.clear_with(0)
        path = self.root / 'image-cover.pdf'
        doc = pymupdf.open()
        doc.new_page(width=100, height=100).insert_image((30, 30, 50, 50), pixmap=pix)
        doc.save(path)
        doc.close()
        pdf = PdfDocument(path)
        try:
            pdf.cover_region(0, (30, 30, 50, 50))
            self.assertGreater(pdf.render(0, 1).pixel(40, 40)[0], 240)
            self.assertTrue(pdf.undo())
            self.assertLess(pdf.render(0, 1).pixel(40, 40)[0], 10)
            self.assertTrue(pdf.redo())
            self.assertGreater(pdf.render(0, 1).pixel(40, 40)[0], 240)
        finally:
            pdf.close()


if __name__ == '__main__':
    unittest.main()
