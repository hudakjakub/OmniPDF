import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from omnipdf.windows_ocr import recognize


class ProjectLayoutTests(unittest.TestCase):
    def test_ocr_helper_is_packaged_with_its_module(self):
        with patch('omnipdf.windows_ocr.subprocess.run') as run:
            run.return_value = subprocess.CompletedProcess([], 0, b'[]', b'')
            self.assertEqual(recognize('image.png'), [])
        arguments = run.call_args.args[0]
        script = Path(arguments[arguments.index('-File') + 1])
        self.assertTrue(script.is_file())
        self.assertEqual(script.parent.name, 'omnipdf')


if __name__ == '__main__':
    unittest.main()
