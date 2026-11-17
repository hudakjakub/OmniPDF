import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pymupdf
from PySide6.QtWidgets import QApplication

from pdf_document import PdfDocument
from native_print import print_native, run_helper


class NativePrintTests(unittest.TestCase):
    def test_helper_exit_and_start_failure(self):
        app = QApplication.instance() or QApplication([])
        self.assertEqual(run_helper([sys.executable, '-c', 'raise SystemExit(1)']), 1)
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(RuntimeError):
                run_helper([Path(folder) / 'missing.exe'])

    def test_passes_rendered_edited_pages_and_cleans_up(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / 'source.pdf'
            with pymupdf.open() as pdf:
                for text in ('First page', 'Second page'):
                    pdf.new_page().insert_text((40, 50), text)
                pdf.save(source)
            document = PdfDocument(source)
            try:
                before = document.render(0, 1).samples
                document.document[0].insert_text((40, 90), 'Unsaved change')
                captured = {}
                def run(args):
                    captured['folder'] = Path(args[1])
                    captured['title'] = args[2]
                    captured['pages'] = sorted(captured['folder'].glob('*.png'))
                    self.assertEqual(len(captured['pages']), 2)
                    self.assertTrue(all(page.stat().st_size for page in captured['pages']))
                    self.assertNotEqual(before, document.render(0, 1).samples)
                    self.assertEqual(pymupdf.Pixmap(str(captured['pages'][0])).samples, document.render(0, 300 / 72).samples)
                    return 0
                with patch('native_print.run_helper', side_effect=run):
                    self.assertTrue(print_native(document, Path('helper.exe')))
                self.assertFalse(captured['folder'].exists())
                self.assertEqual(captured['title'], source.name)
            finally:
                document.close()

    def test_failure_does_not_succeed_or_leave_temporary_pages(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / 'source.pdf'
            with pymupdf.open() as pdf:
                pdf.new_page()
                pdf.save(source)
            document = PdfDocument(source)
            try:
                captured = []
                def fail(args):
                    captured.append(Path(args[1]))
                    return 2
                with patch('native_print.run_helper', side_effect=fail):
                    with self.assertRaises(RuntimeError):
                        print_native(document, Path('helper.exe'))
                self.assertFalse(captured[0].exists())
                with patch('native_print.run_helper', return_value=1):
                    self.assertFalse(print_native(document, Path('helper.exe')))
            finally:
                document.close()


if __name__ == '__main__':
    unittest.main()
