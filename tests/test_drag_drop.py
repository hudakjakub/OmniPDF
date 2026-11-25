import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pymupdf
from PySide6.QtCore import QAbstractAnimation, QMimeData, QPoint, QPointF, Qt, QUrl
from PySide6.QtGui import QDragEnterEvent, QDragLeaveEvent, QDragMoveEvent, QDropEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

from omnipdf.main import Editor


class DragDropTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.source = self.root / 'source.pdf'
        self.target = self.root / 'faktúra 2.PDF'
        with pymupdf.open() as doc:
            page = doc.new_page(width=500, height=700)
            page.insert_text((50, 80), 'INVOICE 12345', fontsize=20)
            doc.save(self.source)
            doc.save(self.target)
            page.get_pixmap().save(self.root / 'scan.PNG')
        self.window = Editor()
        self.window._auto_ocr = lambda document, index: None
        self.window._error = lambda error: self.fail(str(error))
        self.window.show()
        self.app.processEvents()

    def tearDown(self):
        self.window.auto_apply_timer.stop()
        self.window.view.raster_timer.stop()
        if self.window.pdf:
            self.window.pdf.close()
            self.window.pdf = None
        self.window.pending = False
        self.window.close()
        self.app.processEvents()
        self.temp.cleanup()

    def drop(self, widget, urls, actions=Qt.DropAction.CopyAction):
        mime = QMimeData()
        mime.setUrls(urls)
        point = QPoint(10, 10)
        enter = QDragEnterEvent(point, actions, mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        self.app.sendEvent(widget, enter)
        move = QDragMoveEvent(point, actions, mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        self.app.sendEvent(widget, move)
        drop = QDropEvent(QPointF(point), actions, mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        self.app.sendEvent(widget, drop)
        self.app.processEvents()
        return enter, move, drop

    def local(self, path):
        return QUrl.fromLocalFile(str(path))

    def open_source(self):
        self.window.open_file(path=self.source)
        self.app.processEvents()

    def test_drop_on_window_and_empty_area(self):
        for widget in (self.window, self.window.empty):
            with self.subTest(widget=widget):
                events = self.drop(widget, [self.local(self.target)], Qt.DropAction.CopyAction | Qt.DropAction.MoveAction)
                self.assertTrue(all(event.isAccepted() for event in events))
                self.assertTrue(all(event.dropAction() == Qt.DropAction.CopyAction for event in events))
                self.assertEqual(self.window.pdf.source, self.target)

    def test_drop_feedback_animates_and_clears_on_leave_drop_and_rejection(self):
        window = self.window
        mime = QMimeData()
        mime.setUrls([self.local(self.target)])
        def enter(widget, urls=mime):
            event = QDragEnterEvent(QPoint(10, 10), Qt.DropAction.CopyAction, urls,
                                    Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
            self.app.sendEvent(widget, event)
            return event
        self.assertTrue(enter(window).isAccepted())
        self.assertTrue(window.drop_zone.property('dragActive'))
        self.assertEqual(window.drop_animation.state(), QAbstractAnimation.State.Running)
        initial_blur = window.drop_effect.blurRadius()
        QTest.qWait(180)
        self.assertNotEqual(initial_blur, window.drop_effect.blurRadius())
        self.app.sendEvent(window, QDragLeaveEvent())
        enter(window.empty)
        QTest.qWait(80)
        self.assertTrue(window.drop_effect.isEnabled())
        self.app.sendEvent(window.empty, QDragLeaveEvent())
        QTest.qWait(80)
        self.assertFalse(window.drop_effect.isEnabled())
        self.assertEqual(window.drop_animation.state(), QAbstractAnimation.State.Stopped)
        enter(window)
        invalid = QMimeData()
        invalid.setUrls([self.local(self.root / 'missing.pdf')])
        self.assertFalse(enter(window, invalid).isAccepted())
        self.assertFalse(window.drop_effect.isEnabled())
        enter(window)
        with patch.object(window, 'open_file') as open_file:
            self.drop(window, [self.local(self.target)])
            self.assertFalse(window.drop_effect.isEnabled())
            open_file.assert_called_once_with(path=self.target)
        self.open_source()
        enter(window.view.viewport())
        self.assertFalse(window.drop_effect.isEnabled())

    def test_drop_on_preview_and_text_field(self):
        self.open_source()
        self.drop(self.window.view.viewport(), [self.local(self.target)])
        self.assertEqual(self.window.pdf.source, self.target)
        self.window.select_text(self.window.pdf.spans(0)[0])
        self.drop(self.window.text.viewport(), [self.local(self.root / 'scan.PNG')])
        self.assertEqual(self.window.pdf.source, self.root / 'scan.PNG')
        self.assertNotIn('scan.PNG', self.window.text.toPlainText())

    def test_drop_on_append_card_appends_instead_of_opening_another_document(self):
        self.open_source()
        window = self.window
        original = self.source.read_bytes()
        window.thumbnails.scrollToItem(window.add_pdf_item)
        self.app.processEvents()
        button = window.add_pdf_card.button
        mime = QMimeData()
        mime.setUrls([self.local(self.target)])
        enter = QDragEnterEvent(QPoint(10, 10), Qt.DropAction.CopyAction, mime,
                                Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        self.app.sendEvent(button, enter)
        self.assertTrue(button.property('dragActive'))
        self.app.sendEvent(button, QDragLeaveEvent())
        QTest.qWait(150)
        self.assertFalse(button.property('dragActive'))
        with patch.object(window, 'open_file') as open_file:
            events = self.drop(button, [self.local(self.target)])
            self.assertTrue(all(event.isAccepted() for event in events))
            open_file.assert_not_called()
        self.assertEqual(window.pdf.source, self.source)
        self.assertEqual(window.pdf.page_count, 2)
        self.assertEqual(window.page_index, 1)
        self.assertFalse(button.property('dragActive'))
        self.assertEqual(window.thumbnails.row(window.add_pdf_item), 2)
        window.undo()
        self.assertEqual(window.pdf.page_count, 1)
        window.redo()
        self.assertEqual(window.pdf.page_count, 2)
        self.assertEqual(self.source.read_bytes(), original)
        window.thumbnails.scrollToItem(window.add_pdf_item)
        self.app.processEvents()
        for urls in ([self.local(self.root / 'scan.PNG')], [self.local(self.target), self.local(self.source)]):
            events = self.drop(button, urls)
            self.assertFalse(any(event.isAccepted() for event in events))
            self.assertEqual(window.pdf.page_count, 2)

    def test_invalid_and_busy_drops_preserve_pending_edit(self):
        self.open_source()
        self.window.select_text(self.window.pdf.spans(0)[0])
        self.window.text.setPlainText('INVOICE 54321')
        self.window.auto_apply_timer.stop()
        invalid = [
            [self.local(self.target), self.local(self.source)],
            [QUrl('https://example.com/file.pdf')],
            [self.local(self.root)],
            [self.local(self.root / 'missing.pdf')],
            [self.local(self.root / 'file.txt')],
        ]
        (self.root / 'file.txt').write_text('text')
        for urls in invalid:
            with self.subTest(urls=urls):
                events = self.drop(self.window.text.viewport(), urls)
                self.assertFalse(any(event.isAccepted() for event in events))
                self.assertEqual(self.window.pdf.source, self.source)
                self.assertTrue(self.window.pending)
                self.assertEqual(self.window.text.toPlainText(), 'INVOICE 54321')
        with patch.object(self.window, '_busy', return_value=True):
            self.drop(self.window.view.viewport(), [self.local(self.target)])
        self.assertEqual(self.window.pdf.source, self.source)
        self.assertTrue(self.window.pending)

    def test_drop_obeys_cancel_and_discard(self):
        self.open_source()
        self.window.select_text(self.window.pdf.spans(0)[0])
        self.window.text.setPlainText('INVOICE 54321')
        self.window.auto_apply_timer.stop()
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.Cancel):
            self.drop(self.window.view.viewport(), [self.local(self.target)])
        self.assertEqual(self.window.pdf.source, self.source)
        self.assertEqual(self.window.text.toPlainText(), 'INVOICE 54321')
        self.assertTrue(self.window.pending)
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.Discard):
            self.drop(self.window.view.viewport(), [self.local(self.target)])
        self.assertEqual(self.window.pdf.source, self.target)

    def test_escape_cancels_selection_and_flushes_pending(self):
        self.open_source()
        self.window.select_text(self.window.pdf.spans(0)[0])
        self.window.text.setFocus()
        self.window.text.setPlainText('INVOICE 54321')
        QTest.keyClick(self.window.text, Qt.Key.Key_Escape)
        self.assertIsNone(self.window.selection)
        self.assertFalse(self.window.pending)
        self.assertIn('INVOICE 54321', self.window.pdf.document[0].get_text())
        viewport = self.window.view.viewport()
        start = self.window.view.mapFromScene(QPointF(50, 50))
        end = self.window.view.mapFromScene(QPointF(160, 100))
        before = self.window.pdf.document[0].get_text()
        for button in (self.window.region_button, self.window.cover_button):
            with self.subTest(tool=button.toolTip()):
                button.click()
                self.assertTrue(button.isChecked())
                QTest.keyClick(button, Qt.Key.Key_Escape)
                self.assertFalse(button.isChecked())
                self.assertFalse(self.window.view.region_mode)
                button.click()
                QTest.mousePress(viewport, Qt.MouseButton.LeftButton, pos=start)
                QTest.mouseMove(viewport, end)
                self.assertIsNotNone(self.window.view.start_point)
                QTest.keyClick(self.window.view, Qt.Key.Key_Escape)
                QTest.mouseRelease(viewport, Qt.MouseButton.LeftButton, pos=end)
                self.assertFalse(self.window.region_button.isChecked())
                self.assertFalse(self.window.cover_button.isChecked())
                self.assertFalse(self.window.view.region_mode)
                self.assertIsNone(self.window.selection)
                self.assertIsNone(self.window.view.start_point)
                self.assertIsNone(self.window.view.anchor_cursor)
                self.assertFalse(self.window.view.dragging_text)
                self.assertEqual(before, self.window.pdf.document[0].get_text())


if __name__ == '__main__':
    unittest.main()
