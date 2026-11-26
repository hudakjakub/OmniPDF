from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from scripts.build_windows import ROOT, build_environment, validate_version, version_metadata, write_windows_icon


class BuildTests(unittest.TestCase):
    def test_version_and_tag(self):
        self.assertEqual(validate_version('1.2.3', 'v1.2.3'), (1, 2, 3, 0))
        for version, tag in [('1.2.3', 'v1.2.4'), ('1.2.3-rc1', None), ('01.2.3', None), ('1.٢.3', None), ('65536.0.0', None)]:
            with self.subTest(version=version, tag=tag), self.assertRaises(ValueError):
                validate_version(version, tag)

    def test_metadata(self):
        metadata = version_metadata('1.2.3')
        self.assertIn('filevers=(1, 2, 3, 0)', metadata)
        self.assertIn("StringStruct('ProductVersion', '1.2.3')", metadata)

    def test_build_does_not_bundle_unrelated_host_tool_libraries(self):
        with patch.dict('os.environ', {'PATH': 'C:/host-tools/poppler/bin'}):
            self.assertNotIn('poppler', build_environment()['PATH'])

    def test_icon_has_antialiased_images_at_windows_shell_sizes(self):
        from PySide6.QtCore import QBuffer
        from PySide6.QtGui import QImageReader
        from PySide6.QtWidgets import QApplication

        with patch.dict('os.environ', {'QT_QPA_PLATFORM': 'offscreen'}):
            app = QApplication.instance() or QApplication([])
        with TemporaryDirectory() as folder:
            path = Path(folder) / 'omni.ico'
            write_windows_icon(ROOT / 'omnipdf' / 'assets' / 'omni.svg', path)
            buffer = QBuffer()
            buffer.setData(path.read_bytes())
        reader = QImageReader(buffer, b'ico')
        sizes = set()
        for index in range(reader.imageCount()):
            self.assertTrue(reader.jumpToImage(index))
            image = reader.read()
            self.assertEqual(image.width(), image.height())
            sizes.add(image.width())
            if image.width() in (16, 32, 48):
                self.assertTrue(any(0 < image.pixelColor(x, y).alpha() < 255
                                    for x in range(image.width()) for y in range(image.height())))
        self.assertTrue({16, 20, 24, 32, 40, 48, 60, 64, 72, 96, 256} <= sizes)
