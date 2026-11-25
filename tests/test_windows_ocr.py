import subprocess
import unittest
from unittest.mock import patch

from omnipdf.windows_ocr import recognize


class WindowsOcrTests(unittest.TestCase):
    def setUp(self):
        language = patch('omnipdf.i18n.language', return_value='sk')
        language.start()
        self.addCleanup(language.stop)

    @patch("omnipdf.windows_ocr.subprocess.run")
    def test_line_result(self, run):
        run.return_value = subprocess.CompletedProcess([], 0, b'[{"text":"invoice","bbox":[1,2,3,4]}]', b'')
        self.assertEqual(recognize("image.png"), [{"text": "invoice", "bbox": (1, 2, 3, 4)}])

    @patch("omnipdf.windows_ocr.subprocess.run")
    def test_missing_language(self, run):
        run.return_value = subprocess.CompletedProcess([], 1, b'', b'NO_OCR_LANGUAGE')
        with self.assertRaisesRegex(RuntimeError, "jazyk"):
            recognize("image.png")

    @patch("omnipdf.windows_ocr.subprocess.run")
    def test_missing_language_in_english(self, run):
        run.return_value = subprocess.CompletedProcess([], 1, b'', b'NO_OCR_LANGUAGE')
        with patch('omnipdf.i18n.language', return_value='en'):
            with self.assertRaisesRegex(RuntimeError, "No Windows OCR language"):
                recognize("image.png")

    @patch("omnipdf.windows_ocr.subprocess.run")
    def test_invalid_result(self, run):
        run.return_value = subprocess.CompletedProcess([], 0, b'invalid', b'')
        with self.assertRaisesRegex(RuntimeError, "neplatn"):
            recognize("image.png")


if __name__ == "__main__":
    unittest.main()
