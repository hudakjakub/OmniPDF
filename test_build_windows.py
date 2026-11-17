import unittest
from scripts.build_windows import validate_version, version_metadata


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
