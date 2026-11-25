import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pymupdf
from PySide6.QtWidgets import QApplication

from main import Editor
from pdf_document import PdfDocument


class SelectionPreviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_selection_edit_clear_and_rotated_clip(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'preview.pdf'
            with pymupdf.open() as doc:
                page = doc.new_page(width=300, height=200)
                page.insert_text((5, 20), 'Selected text', fontsize=12)
                page.set_rotation(90)
                doc.save(path)
            window = Editor()
            window._error = lambda error: self.fail(str(error))
            window.show()
            window.open_file(path=path)
            self.app.processEvents()
            try:
                span = window.pdf.spans(0)[0]
                with patch.object(window.pdf, 'render', wraps=window.pdf.render) as render:
                    window.select_text(span)
                clip = render.call_args.kwargs['clip']
                self.assertTrue(window.pdf.document[0].rect.contains(clip))
                self.assertFalse(window.selection_preview.isHidden())
                self.assertFalse(window.selection_preview.pixmap().isNull())
                before = window.selection_preview.pixmap().toImage()
                window.text.setPlainText('Changed text')
                self.assertTrue(window.apply_change())
                self.assertNotEqual(before, window.selection_preview.pixmap().toImage())
                window.clear_selection()
                self.assertTrue(window.selection_preview.isHidden())
                window.select_range(window.pdf.characters(0)[:3])
                self.assertTrue(window.selection_preview.isHidden())
                window.clear_selection()
                self.assertTrue(window.selection_preview.isHidden())
            finally:
                window.pdf.close()
                window.pdf = None
                window.close()

    def test_clip_hides_empty_signature(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'signature.pdf'
            with pymupdf.open() as doc:
                page = doc.new_page(width=200, height=200)
                widget = pymupdf.Widget()
                widget.field_name = 'signature'
                widget.field_type = pymupdf.PDF_WIDGET_TYPE_SIGNATURE
                widget.rect = pymupdf.Rect(20, 20, 120, 60)
                widget.fill_color = (1, 0.5, 0)
                page.add_widget(widget)
                doc.save(path)
            document = PdfDocument(path)
            try:
                pix = document.render(0, 2, clip=pymupdf.Rect(10, 10, 130, 70))
                self.assertEqual((pix.width, pix.height), (240, 120))
                self.assertEqual(set(pix.samples), {255})
            finally:
                document.close()


if __name__ == '__main__':
    unittest.main()
