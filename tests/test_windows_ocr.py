import subprocess
import unittest
from unittest.mock import patch

from omnipdf.windows_ocr import recognize


class WindowsOcrTests(unittest.TestCase):
    def setUp(self):
        language = patch('omnipdf.i18n.language', return_value='sk')
        language.start()
        self.addCleanup(language.stop)

    def mock_process(self, popen, code, stdout=b'', stderr=b''):
        process = popen.return_value.__enter__.return_value
        process.communicate.return_value = stdout, stderr
        process.returncode = code
        process.poll.return_value = code
        return process

    @patch("omnipdf.windows_ocr.subprocess.Popen")
    def test_line_result(self, popen):
        self.mock_process(popen, 0, b'[{"text":"invoice","bbox":[1,2,3,4]}]')
        self.assertEqual(recognize("image.png"), [{"text": "invoice", "bbox": (1, 2, 3, 4)}])

    @patch("omnipdf.windows_ocr.subprocess.Popen")
    def test_missing_language(self, popen):
        self.mock_process(popen, 1, stderr=b'NO_OCR_LANGUAGE')
        with self.assertRaisesRegex(RuntimeError, "jazyk"):
            recognize("image.png")

    @patch("omnipdf.windows_ocr.subprocess.Popen")
    def test_missing_language_in_english(self, popen):
        self.mock_process(popen, 1, stderr=b'NO_OCR_LANGUAGE')
        with patch('omnipdf.i18n.language', return_value='en'):
            with self.assertRaisesRegex(RuntimeError, "No Windows OCR language"):
                recognize("image.png")

    @patch("omnipdf.windows_ocr.subprocess.Popen")
    def test_invalid_result(self, popen):
        self.mock_process(popen, 0, b'invalid')
        with self.assertRaisesRegex(RuntimeError, "neplatn"):
            recognize("image.png")

    @patch("omnipdf.windows_ocr.subprocess.Popen")
    def test_cancelling_ocr_terminates_the_process(self, popen):
        process = self.mock_process(popen, None)
        process.communicate.side_effect = subprocess.TimeoutExpired('ocr', 0.2)
        cancelled = iter((False, True))
        self.assertEqual(recognize('image.png', cancelled=lambda: next(cancelled)), [])
        process.kill.assert_called_once()


if __name__ == "__main__":
    unittest.main()
