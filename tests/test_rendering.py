import tempfile
import unittest
from pathlib import Path

import pymupdf

from omnipdf.pdf_document import PdfDocument


class RenderingTests(unittest.TestCase):
    def test_signed_widget_remains_visible_next_to_empty_signature(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'signed-widgets.pdf'
            with pymupdf.open() as source:
                page = source.new_page(width=300, height=200)
                for name, rect, color in [('signed', (20, 20, 120, 60), (1, 0, 0)),
                                          ('empty', (20, 90, 120, 130), (0, 0, 1))]:
                    widget = pymupdf.Widget()
                    widget.field_name = name
                    widget.field_type = pymupdf.PDF_WIDGET_TYPE_SIGNATURE
                    widget.rect = pymupdf.Rect(rect)
                    widget.fill_color = color
                    page.add_widget(widget)
                signed = next(page.widgets())
                xref = source.get_new_xref()
                source.update_object(xref, '<< /Type /Sig /ByteRange [0 1 2 3] /Contents <00> >>')
                source.xref_set_key(signed.xref, 'V', f'{xref} 0 R')
                source.save(path)
            pdf = PdfDocument(path, allow_signed=True)
            try:
                original = pdf.document[0].get_pixmap()
                rendered = pdf.render(0, 1)
                self.assertNotEqual(original.pixel(21, 21), (255, 255, 255))
                self.assertEqual(rendered.pixel(21, 21), original.pixel(21, 21))
                self.assertEqual(rendered.pixel(21, 91), (255, 255, 255))
            finally:
                pdf.close()

    def test_hidden_layer_stays_hidden_with_empty_signature(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'hidden-layer.pdf'
            with pymupdf.open() as source:
                page = source.new_page(width=300, height=300)
                hidden = source.add_ocg('Hidden', on=False)
                page.insert_text((30, 100), 'Opis', fontsize=40, oc=hidden)
                signature = pymupdf.Widget()
                signature.field_name = 'signature'
                signature.field_type = pymupdf.PDF_WIDGET_TYPE_SIGNATURE
                signature.rect = pymupdf.Rect(20, 150, 120, 190)
                page.add_widget(signature)
                source.save(path)
            document = PdfDocument(path)
            try:
                self.assertEqual(set(document.render(0, 1).samples), {255})
                self.assertFalse(document.document.get_ocgs()[hidden]['on'])
                self.assertFalse(document.dirty)
            finally:
                document.close()

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
