import tempfile
import unittest
from pathlib import Path

import pymupdf

from pdf_document import PdfDocument


class RenderingTests(unittest.TestCase):
    def test_empty_signature_hidden_only_in_preview(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'widgets.pdf'
            with pymupdf.open() as source:
                page = source.new_page(width=300, height=300)
                signature = pymupdf.Widget()
                signature.field_name = 'signature'
                signature.field_type = pymupdf.PDF_WIDGET_TYPE_SIGNATURE
                signature.rect = pymupdf.Rect(20, 20, 120, 60)
                signature.fill_color = (1, 0.5, 0)
                page.add_widget(signature)
                text = pymupdf.Widget()
                text.field_name = 'text'
                text.field_type = pymupdf.PDF_WIDGET_TYPE_TEXT
                text.field_value = 'Visible value'
                text.rect = pymupdf.Rect(20, 90, 180, 120)
                page.add_widget(text)
                page.add_rect_annot(pymupdf.Rect(20, 150, 180, 180))
                source.save(path)

            document = PdfDocument(path)
            try:
                page = document.document[0]
                original = page.get_pixmap()
                rendered = document.render(0, 1)

                def region(pixmap, x0, y0, x1, y1):
                    return b''.join(pixmap.samples[y * pixmap.stride + x0 * 3:y * pixmap.stride + x1 * 3]
                                    for y in range(y0, y1))

                signature_before = region(original, 20, 20, 120, 60)
                signature_after = region(rendered, 20, 20, 120, 60)
                self.assertNotEqual(signature_before, signature_after)
                self.assertEqual(set(signature_after), {255})
                for bounds in ((20, 90, 180, 120), (20, 150, 180, 180)):
                    self.assertEqual(region(original, *bounds), region(rendered, *bounds))
                    self.assertNotEqual(set(region(rendered, *bounds)), {255})
                self.assertEqual([w.field_type for w in page.widgets()],
                                 [pymupdf.PDF_WIDGET_TYPE_SIGNATURE, pymupdf.PDF_WIDGET_TYPE_TEXT])
                self.assertEqual(page.get_pixmap().samples, original.samples)
                self.assertFalse(document.dirty)
            finally:
                document.close()


if __name__ == '__main__':
    unittest.main()
