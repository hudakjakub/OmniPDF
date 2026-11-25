import os
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pymupdf
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from omnipdf.main import PageView


class ContinuousViewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.doc = pymupdf.open()
        self.doc.new_page(width=300, height=400)
        self.doc.new_page(width=200, height=300)
        self.view = PageView()
        self.view.resize(400, 220)
        self.view.show()
        self.view.configure_pages([(300, 400), (200, 300)])
        self.view.set_page(self.doc[0].get_pixmap(), 1, self.doc[0], [], page_index=0)
        self.app.processEvents()

    def tearDown(self):
        self.view.raster_timer.stop()
        self.view.close()
        self.doc.close()

    def test_layout_navigation_cache_and_fit(self):
        view = self.view
        self.assertEqual([(r.x(), r.y(), r.width(), r.height()) for r in view.page_rects],
                         [(24, 24, 300, 400), (74, 448, 200, 300)])
        self.assertFalse(view.configure_pages([(300, 400), (200, 300)]))
        self.assertGreater(view.verticalScrollBar().maximum(), 0)
        view.scroll_to_page(1)
        self.app.processEvents()
        self.assertEqual(view.current_visible_page(), 1)
        self.assertIn(1, view.visible_page_indices())
        view.update_page_raster(1, self.doc[1].get_pixmap(), 1)
        self.assertEqual(view.page_scales[1], 1)
        view.evict_page_raster(1)
        self.assertTrue(view.page_items[1].pixmap().isNull())
        scene = view.sceneRect()
        view.fit_width()
        self.app.processEvents()
        self.assertEqual(view.sceneRect(), scene)
        self.assertEqual(view.horizontalScrollBar().maximum(), 0)

    def test_click_rotated_second_page_and_region_coordinates(self):
        page = self.doc[1]
        page.set_rotation(90)
        self.view.configure_pages([(300, 400), (300, 200)])
        self.view.set_page(self.doc[0].get_pixmap(), 1, self.doc[0], [], page_index=0)
        self.view.page_requested.connect(lambda i: self.view.set_page(None, 1, self.doc[i], [], page_index=i))
        self.view.scroll_to_page(1)
        self.app.processEvents()
        self.view.set_region_mode(True)
        regions = []
        self.view.region.connect(regions.append)
        # Native rectangle (20, 30)-(60, 80), rotated into display coordinates.
        display = pymupdf.Rect(20, 30, 60, 80) * page.rotation_matrix
        rect = self.view.page_rects[1]
        start = self.view.mapFromScene(rect.x() + display.x0, rect.y() + display.y0)
        end = self.view.mapFromScene(rect.x() + display.x1, rect.y() + display.y1)
        QTest.mousePress(self.view.viewport(), Qt.MouseButton.LeftButton, pos=start)
        QTest.mouseRelease(self.view.viewport(), Qt.MouseButton.LeftButton, pos=end)
        self.assertEqual(self.view.active_index, 1)
        self.assertEqual(len(regions), 1)
        for actual, expected in zip(regions[0], (20, 30, 60, 80)):
            self.assertAlmostEqual(actual, expected, delta=2)


if __name__ == '__main__':
    unittest.main()
