import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pymupdf
from PySide6.QtWidgets import QApplication

from main import Editor, PageView


class FitWidthTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_fit_at_various_widths_and_after_zoom(self):
        view = PageView()
        doc = pymupdf.open()
        page = doc.new_page(width=595, height=842)
        page.insert_text((50, 80), 'Invoice')
        pixmap = page.get_pixmap()
        view.resize(800, 600)
        view.show()
        self.app.processEvents()
        view.set_page(pixmap, 1, page, [])
        view.highlight_boxes([pymupdf.Rect(50, 60, 100, 85)])
        highlight = view.selection_item
        for width in (320, 800, 1400):
            with self.subTest(width=width):
                view.resize(width, 600)
                view.zoom(1.25)
                view.fit_width()
                self.app.processEvents()
                bounds = view.mapFromScene(view.sceneRect()).boundingRect()
                self.assertGreaterEqual(bounds.left(), -1)
                self.assertLessEqual(bounds.right(), view.viewport().width())
                self.assertEqual(view.horizontalScrollBar().maximum(), 0)
                self.assertIs(view.selection_item, highlight)
        view.raster_timer.stop()
        view.close()
        doc.close()

    def test_editor_fit_button_after_zoom(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'invoice.pdf'
            with pymupdf.open() as doc:
                doc.new_page(width=595, height=842).insert_text((50, 80), 'Invoice')
                doc.save(path)
            window = Editor()
            window.show()
            window.open_file(path=path)
            self.app.processEvents()
            window.plus_button.click()
            window.fit_button.click()
            self.app.processEvents()
            view = window.view
            bounds = view.mapFromScene(view.sceneRect()).boundingRect()
            self.assertGreaterEqual(bounds.left(), -1)
            self.assertLessEqual(bounds.right(), view.viewport().width())
            self.assertEqual(view.horizontalScrollBar().maximum(), 0)
            view.raster_timer.stop()
            window.pdf.close()
            window.pdf = None
            window.close()


if __name__ == '__main__':
    unittest.main()
