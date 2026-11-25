import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from omnipdf.windows_ocr import recognize
from omnipdf.main import project_root


class ProjectLayoutTests(unittest.TestCase):
    def test_frozen_resources_use_bundle_root(self):
        with patch.object(sys, '_MEIPASS', r'C:\example\bundle', create=True):
            self.assertEqual(project_root(), Path(r'C:\example\bundle'))

    def test_package_entrypoint_runs_smoke_test(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'smoke.json'
            env = {**os.environ, 'QT_QPA_PLATFORM': 'offscreen'}
            result = subprocess.run([sys.executable, '-m', 'omnipdf', '--smoke-test', '--output', str(output)],
                                    capture_output=True, text=True, env=env, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            data = json.loads(output.read_text(encoding='utf-8'))
            self.assertTrue(data['resources_ok'])
            self.assertTrue(data['pdf_render_ok'])

    def test_ocr_helper_is_packaged_with_its_module(self):
        with patch('omnipdf.windows_ocr.subprocess.Popen') as popen:
            process = popen.return_value.__enter__.return_value
            process.communicate.return_value = b'[]', b''
            process.poll.return_value = 0
            process.returncode = 0
            self.assertEqual(recognize('image.png'), [])
        arguments = popen.call_args.args[0]
        script = Path(arguments[arguments.index('-File') + 1])
        self.assertTrue(script.is_file())
        self.assertEqual(script.parent.name, 'omnipdf')


if __name__ == '__main__':
    unittest.main()
