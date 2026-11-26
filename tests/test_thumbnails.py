import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pymupdf
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QToolButton
from omnipdf.main import Editor, STYLE


class ThumbnailTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setStyleSheet(STYLE)

    def test_visibility_navigation_and_edits(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'invoice.pdf'
            with pymupdf.open() as doc:
                for number in range(3):
                    doc.new_page(width=500, height=700).insert_text((50, 80), f'Page {number + 1}')
                doc.save(source)
            original = source.read_bytes()
            window = Editor()
            window._error = lambda error: self.fail(str(error))
            with patch.object(window, '_auto_ocr'):
                window.show()
                window.open_file(path=source)
                self.app.processEvents()
                self.assertTrue(window.thumbnails.isVisible())
                window.resize(1600, 640)
                self.app.processEvents()
                self.assertFalse(window.thumbnails.isHidden())
                self.assertEqual(window.thumbnails.count(), 4)
                self.assertTrue(all(not window.thumbnails.item(i).icon().isNull() for i in range(3)))
                scrollbar = window.thumbnails.verticalScrollBar()
                first = window.thumbnails.item(0)
                top = window.thumbnails.visualItemRect(first).top()
                scrollbar.setValue(17)
                self.app.processEvents()
                self.assertEqual(top - window.thumbnails.visualItemRect(first).top(), 17)
                viewport = window.thumbnails.viewport()
                position = viewport.rect().center()
                wheel = QWheelEvent(QPointF(position), QPointF(viewport.mapToGlobal(position)),
                                    QPoint(), QPoint(0, -120), Qt.MouseButton.NoButton,
                                    Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
                before = scrollbar.value()
                self.app.sendEvent(viewport, wheel)
                self.app.processEvents()
                self.assertGreater(scrollbar.value(), before)
                self.assertLess(scrollbar.value() - before, window.thumbnails.visualItemRect(first).height())
                self.assertEqual(window.page_index, 0)
                self.assertEqual(window.thumbnails.currentRow(), 0)
                window.thumbnails.scrollToTop()
                window.thumbnails.setCurrentRow(2)
                self.assertEqual(window.page_index, 2)
                with patch.object(window, '_discard_pending', return_value=False):
                    window.thumbnails.setCurrentRow(0)
                    self.assertEqual(window.thumbnails.currentRow(), 2)
                window.previous_button.click()
                self.assertEqual(window.thumbnails.currentRow(), 1)
                before = window.thumbnails.item(1).icon().pixmap(120, 160).toImage()
                window.pdf.cover_region(1, (40, 60, 100, 90))
                window.render_page()
                after = window.thumbnails.item(1).icon().pixmap(120, 160).toImage()
                self.assertNotEqual(before, after)
                window.undo()
                self.assertEqual(before, window.thumbnails.item(1).icon().pixmap(120, 160).toImage())
                window.redo()
                self.assertEqual(after, window.thumbnails.item(1).icon().pixmap(120, 160).toImage())
                for width, height in ((950, 640), (1300, 900), (1600, 900)):
                    window.resize(width, height)
                    self.app.processEvents()
                    self.assertTrue(window.thumbnails.isVisible())
                    self.assertEqual(window.thumbnails.count(), 4)
                    viewport = window.thumbnails.viewport().rect()
                    for index in range(3):
                        row = window.thumbnails.visualItemRect(window.thumbnails.item(index))
                        self.assertLessEqual(abs(row.center().x() - viewport.center().x()), 1)
                        controls = window.thumbnails.itemWidget(window.thumbnails.item(index))
                        self.assertEqual(controls.geometry(), row)
                        for button in controls.findChildren(QToolButton):
                            self.assertTrue(controls.rect().contains(button.geometry()))
                    window.thumbnails.setCurrentRow(0)
                    window.thumbnails.scrollToTop()
                    self.app.processEvents()
                    image = window.thumbnails.viewport().grab().toImage()
                    row = window.thumbnails.visualItemRect(window.thumbnails.item(0))
                    def white(x, y):
                        color = image.pixelColor(x, y)
                        return min(color.red(), color.green(), color.blue()) > 248
                    xs = [x for x in range(row.left(), row.right() + 1) if white(x, row.top() + 80)]
                    ys = [y for y in range(row.top(), row.top() + 40) if white(row.center().x(), y)]
                    self.assertTrue(xs and ys, 'Thumbnail image must remain visible when selected')
                    left, right, top = min(xs) - row.left(), row.right() - max(xs), min(ys) - row.top()
                    self.assertLessEqual(abs(left - right), 1)
                    self.assertLessEqual(abs(left - top), 1)
                    preview_bottom = max(y for y in range(row.top(), row.bottom() + 1)
                                         if white(row.center().x() + 30, y))
                    self.assertTrue(23 <= row.bottom() - preview_bottom <= 32, (row, preview_bottom))
                    controls = window.thumbnails.itemWidget(window.thumbnails.item(0))
                    for button in controls.findChildren(QToolButton):
                        self.assertGreater(button.geometry().top() + row.top(), preview_bottom)
                    margin_x = row.right() - 4
                    self.assertEqual({image.pixelColor(margin_x, y).name()
                                      for y in range(row.top() + top, preview_bottom + 1)}, {'#dce8fb'})
                controls = window.thumbnails.itemWidget(window.thumbnails.item(2))
                QTest.mouseClick(controls, Qt.MouseButton.LeftButton, pos=controls.rect().center())
                self.assertEqual(window.page_index, 2)
                QTest.mouseClick(controls.findChild(QToolButton, 'duplicatePage'), Qt.MouseButton.LeftButton)
                self.assertEqual(window.pdf.page_count, 4)
                self.assertEqual(window.page_index, 3)
                self.assertIn('Page 3', window.pdf.document[3].get_text())
                second_page = window.pdf.document[1].get_text()
                controls = window.thumbnails.itemWidget(window.thumbnails.item(0))
                QTest.mouseClick(controls.findChild(QToolButton, 'deletePage'), Qt.MouseButton.LeftButton)
                self.assertEqual(window.pdf.page_count, 3)
                self.assertEqual(second_page, window.pdf.document[0].get_text())
                window.undo()
                window.undo()
                self.assertEqual(window.pdf.page_count, 3)
                with patch.object(window, '_discard_pending', return_value=False):
                    controls = window.thumbnails.itemWidget(window.thumbnails.item(2))
                    controls.findChild(QToolButton, 'deletePage').click()
                    self.assertEqual(window.pdf.page_count, 3)
                window.delete_page()
                window.delete_page()
                controls = window.thumbnails.itemWidget(window.thumbnails.item(0))
                self.assertTrue(controls.findChild(QToolButton, 'deletePage').isEnabled())
                self.assertTrue(controls.findChild(QToolButton, 'duplicatePage').isEnabled())
                self.assertEqual(original, source.read_bytes())
                window.pdf.close()
                window.pdf = None
                window.close()


if __name__ == '__main__':
    unittest.main()
