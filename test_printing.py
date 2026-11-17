import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pymupdf
from PySide6.QtGui import QPageRanges
from PySide6.QtCore import Qt
from PySide6.QtPrintSupport import QPrinter
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog

from main import Editor


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
        self.window._auto_ocr = lambda *args: None
        self.window._error = lambda error: self.fail(str(error))
        self.window.show()
        self.window.open_file(path=self.source)
        self.app.processEvents()

    def tearDown(self):
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
        with patch('main.QPrintDialog', side_effect=dialog):
            self.window.print_document()
        with pymupdf.open(output) as printed:
            self.assertEqual(printed.page_count, 2)
            for page, expected in zip(printed, ((0, 0, 255), (255, 0, 0))):
                pixmap = page.get_pixmap()
                actual = pixmap.pixel(pixmap.width // 2, pixmap.height // 2)
                self.assertTrue(all(abs(a - b) <= 2 for a, b in zip(actual, expected)), actual)
        self.assertEqual(self.source.read_bytes(), self.original)

    def test_cancelled_dialog_does_not_apply_pending_edit(self):
        self.window.select_text(self.window.pdf.spans(0)[0])
        self.window.text.setPlainText('Pending')
        with patch('main.QPrintDialog') as dialog:
            dialog.return_value.exec.return_value = QDialog.DialogCode.Rejected
            self.window.print_document()
        self.assertTrue(self.window.pending)
        self.assertNotIn('Pending', self.window.pdf.document[0].get_text())
        self.window.clear_selection()

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
        with patch('main.QPrintDialog', side_effect=dialog):
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
        with patch('main.QPrintDialog', side_effect=dialog), patch.object(self.window, '_error') as error:
            self.window.print_document()
        error.assert_called_once()
        self.assertFalse(output.exists())
        self.assertTrue(self.window.pending)
        self.window.clear_selection()

    def test_print_shortcut_and_no_pages(self):
        self.window.view.setFocus()
        with patch('main.QPrintDialog') as dialog:
            dialog.return_value.exec.return_value = QDialog.DialogCode.Rejected
            QTest.keyClick(self.window.view, Qt.Key.Key_P, Qt.KeyboardModifier.ControlModifier)
            dialog.assert_called_once()
        for _index in range(3):
            self.window.delete_page()
        self.assertFalse(self.window.print_button.isEnabled())
        with patch('main.QPrintDialog') as dialog:
            QTest.keyClick(self.window, Qt.Key.Key_P, Qt.KeyboardModifier.ControlModifier)
            dialog.assert_not_called()

    def test_multiple_copies_when_driver_does_not_support_them(self):
        output = self.root / 'copies.pdf'
        def dialog(printer, parent):
            printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
            printer.setOutputFileName(str(output))
            printer.setResolution(72)
            printer.setPrintRange(QPrinter.PrintRange.CurrentPage)
            printer.setCopyCount(2)
            return Mock(exec=Mock(return_value=QDialog.DialogCode.Accepted))
        with patch('main.QPrintDialog', side_effect=dialog):
            self.window.print_document()
        with pymupdf.open(output) as printed:
            self.assertEqual(printed.page_count, 2)

    def test_printer_failure_is_reported(self):
        def dialog(printer, parent):
            printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
            printer.setOutputFileName(str(self.root / 'missing' / 'print.pdf'))
            return Mock(exec=Mock(return_value=QDialog.DialogCode.Accepted))
        with patch('main.QPrintDialog', side_effect=dialog), patch.object(self.window, '_error') as error:
            self.window.print_document()
        error.assert_called_once()
        self.assertEqual(self.source.read_bytes(), self.original)


if __name__ == '__main__':
    unittest.main()
