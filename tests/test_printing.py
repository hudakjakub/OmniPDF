import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pymupdf
from PySide6.QtGui import QPageRanges
from PySide6.QtCore import Qt, QTimer
from PySide6.QtPrintSupport import QPrinter, QPrintPreviewWidget
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QPushButton

from omnipdf.main import Editor


class PrintingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / 'source.pdf'
        with pymupdf.open() as doc:
            for color in ((1, 0, 0), (0, 1, 0), (0, 0, 1)):
                page = doc.new_page(width=200, height=200)
                page.draw_rect(page.rect, color=None, fill=color)
                page.insert_text((20, 60), 'Test')
            doc.save(self.source)
        self.original = self.source.read_bytes()
        self.window = Editor()
        self.helper_patch = patch('omnipdf.main.helper_ready', return_value=False)
        self.helper_patch.start()
        self.preview_patch = patch.object(self.window, '_show_print_preview', return_value=True)
        self.preview_patch.start()
        self.window._auto_ocr = lambda *args: None
        self.window._error = lambda error: self.fail(str(error))
        self.window.show()
        self.window.open_file(path=self.source)
        self.app.processEvents()

    def tearDown(self):
        self.helper_patch.stop()
        self.preview_patch.stop()
        self.window.pdf.close()
        self.window.pdf = None
        self.window.close()
        self.temp.cleanup()

    def test_print_selected_pages_in_reverse_order(self):
        output = self.root / 'printed.pdf'
        def dialog(printer, parent):
            printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
            printer.setOutputFileName(str(output))
            printer.setResolution(72)
            printer.setPrintRange(QPrinter.PrintRange.PageRange)
            printer.setPageRanges(QPageRanges.fromString('1,3'))
            printer.setPageOrder(QPrinter.PageOrder.LastPageFirst)
            return Mock(exec=Mock(return_value=QDialog.DialogCode.Accepted))
        with patch('omnipdf.main.QPrintDialog', side_effect=dialog):
            self.window.print_document()
        with pymupdf.open(output) as printed:
            self.assertEqual(printed.page_count, 2)
            for page, expected in zip(printed, ((0, 0, 255), (255, 0, 0))):
                pixmap = page.get_pixmap()
                actual = pixmap.pixel(pixmap.width // 2, pixmap.height // 2)
                self.assertTrue(all(abs(a - b) <= 2 for a, b in zip(actual, expected)), actual)
        self.assertEqual(self.source.read_bytes(), self.original)

    def test_cancelled_dialog_does_not_print(self):
        self.window.select_text(self.window.pdf.spans(0)[0])
        self.window.text.setPlainText('Best')
        with patch('omnipdf.main.QPrintDialog') as dialog:
            dialog.return_value.exec.return_value = QDialog.DialogCode.Rejected
            self.window.print_document()
        self.assertFalse(self.window.pending)
        self.assertIn('Best', self.window.pdf.document[0].get_text())
        self.window.clear_selection()

    def test_cancelling_preview_does_not_open_print_dialog(self):
        self.preview_patch.stop()
        with patch.object(self.window, '_show_print_preview', return_value=False), patch('omnipdf.main.QPrintDialog') as dialog:
            self.window.print_document()
        dialog.assert_not_called()

    def test_preview_shows_document_and_allows_page_navigation(self):
        self.preview_patch.stop()
        observed = {}
        def inspect():
            dialog = self.window.findChild(QDialog, 'printPreview')
            if dialog is None:
                observed['error'] = 'Preview dialog not found'
                return
            preview = dialog.findChild(QPrintPreviewWidget, 'printPreviewPages')
            observed['pages'] = preview.pageCount()
            observed['current'] = preview.currentPage()
            image = preview.grab().toImage()
            observed['has_red'] = any(image.pixelColor(x, y).red() > 200 and image.pixelColor(x, y).green() < 80
                                      for y in range(0, image.height(), 10) for x in range(0, image.width(), 10))
            dialog.findChild(QPushButton, 'previewNext').click()
            observed['next'] = preview.currentPage()
            dialog.reject()
        QTimer.singleShot(250, inspect)
        printer = QPrinter()
        printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
        printer.setOutputFileName(str(self.root / 'preview.pdf'))
        self.assertFalse(self.window._show_print_preview(printer))
        self.assertEqual(observed, {'pages': 3, 'current': 1, 'has_red': True, 'next': 2})

    def test_print_current_page_applies_pending_edit(self):
        output = self.root / 'current.pdf'
        self.window.change_page(1)
        self.window.select_text(self.window.pdf.spans(1)[0])
        self.window.text.setPlainText('Best')
        def dialog(printer, parent):
            printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
            printer.setOutputFileName(str(output))
            printer.setResolution(72)
            printer.setPrintRange(QPrinter.PrintRange.CurrentPage)
            return Mock(exec=Mock(return_value=QDialog.DialogCode.Accepted))
        with patch('omnipdf.main.QPrintDialog', side_effect=dialog):
            self.window.print_document()
        self.assertIn('Best', self.window.pdf.document[1].get_text())
        self.assertFalse(self.window.pending)
        with pymupdf.open(output) as printed:
            self.assertEqual(printed.page_count, 1)
            pixmap = printed[0].get_pixmap()
            pixel = pixmap.pixel(pixmap.width // 2, pixmap.height // 2)
            self.assertGreater(pixel[1], 250)
            self.assertLess(pixel[0], 5)
        self.assertEqual(self.source.read_bytes(), self.original)

    def test_invalid_pending_edit_prevents_printing(self):
        output = self.root / 'blocked.pdf'
        self.window.select_text(self.window.pdf.spans(0)[0])
        self.window.text.setPlainText('X' * 2000)
        def dialog(printer, parent):
            printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
            printer.setOutputFileName(str(output))
            return Mock(exec=Mock(return_value=QDialog.DialogCode.Accepted))
        with patch('omnipdf.main.QPrintDialog', side_effect=dialog), patch.object(self.window, '_error') as error:
            self.window.print_document()
        error.assert_called_once()
        self.assertFalse(output.exists())
        self.assertTrue(self.window.pending)
        self.window.clear_selection()

    def test_print_shortcut_and_no_pages(self):
        self.window.view.setFocus()
        with patch('omnipdf.main.QPrintDialog') as dialog:
            dialog.return_value.exec.return_value = QDialog.DialogCode.Rejected
            QTest.keyClick(self.window.view, Qt.Key.Key_P, Qt.KeyboardModifier.ControlModifier)
            dialog.assert_called_once()
        for _index in range(3):
            self.window.delete_page()
        self.assertFalse(self.window.print_button.isEnabled())
        with patch('omnipdf.main.QPrintDialog') as dialog:
            QTest.keyClick(self.window, Qt.Key.Key_P, Qt.KeyboardModifier.ControlModifier)
            dialog.assert_not_called()

    def test_windows_helper_opens_system_preview_with_current_document(self):
        with patch('omnipdf.main.sys.platform', 'win32'), patch('omnipdf.main.Path.is_file', return_value=True), patch('omnipdf.main.helper_ready', return_value=True), \
             patch('omnipdf.main.print_native', return_value=True) as native, patch('omnipdf.main.QPrintDialog') as dialog:
            self.window.print_document()
        native.assert_called_once()
        self.assertIs(native.call_args.args[0], self.window.pdf)
        dialog.assert_not_called()

    def test_unavailable_windows_helper_keeps_existing_print_dialog(self):
        with patch('omnipdf.main.sys.platform', 'win32'), patch('omnipdf.main.Path.is_file', return_value=True), \
             patch('omnipdf.main.helper_ready', return_value=False), patch('omnipdf.main.QPrintDialog') as dialog:
            dialog.return_value.exec.return_value = QDialog.DialogCode.Rejected
            self.window.print_document()
        dialog.assert_called_once()

    def test_multiple_copies_when_driver_does_not_support_them(self):
        output = self.root / 'copies.pdf'
        def dialog(printer, parent):
            printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
            printer.setOutputFileName(str(output))
            printer.setResolution(72)
            printer.setPrintRange(QPrinter.PrintRange.CurrentPage)
            printer.setCopyCount(2)
            return Mock(exec=Mock(return_value=QDialog.DialogCode.Accepted))
        with patch('omnipdf.main.QPrintDialog', side_effect=dialog):
            self.window.print_document()
        with pymupdf.open(output) as printed:
            self.assertEqual(printed.page_count, 2)

    def test_printer_failure_is_reported(self):
        def dialog(printer, parent):
            printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
            printer.setOutputFileName(str(self.root / 'missing' / 'print.pdf'))
            return Mock(exec=Mock(return_value=QDialog.DialogCode.Accepted))
        with patch('omnipdf.main.QPrintDialog', side_effect=dialog), patch.object(self.window, '_error') as error:
            self.window.print_document()
        error.assert_called_once()
        self.assertEqual(self.source.read_bytes(), self.original)


if __name__ == '__main__':
    unittest.main()
