import ctypes
import unittest
from unittest.mock import patch

import window_chrome


class WindowChromeTests(unittest.TestCase):
    @patch("window_chrome.sys.platform", "win32")
    @patch("window_chrome.ctypes.WinDLL", create=True)
    def test_title_bar_colors_and_legacy_fallback(self, dll):
        set_attribute = dll.return_value.DwmSetWindowAttribute
        calls = []

        def record(hwnd, attribute, value, size):
            calls.append((hwnd, attribute, ctypes.cast(value, ctypes.POINTER(ctypes.c_uint32)).contents.value, size))
            return -1 if attribute == 20 else 0

        set_attribute.side_effect = record
        hwnd = 0x123456789
        window_chrome.configure_title_bar(hwnd)
        self.assertEqual(calls, [
            (hwnd, 20, 0, 4), (hwnd, 19, 0, 4),
            (hwnd, 34, 0xE8E3DC, 4), (hwnd, 35, 0xFFFFFF, 4),
            (hwnd, 36, 0x423624, 4),
        ])
        self.assertEqual(set_attribute.argtypes[0], ctypes.c_void_p)
        self.assertEqual(set_attribute.restype, ctypes.c_int32)
        dll.assert_called_once_with("dwmapi")

    @patch("window_chrome.sys.platform", "win32")
    @patch("window_chrome.ctypes.WinDLL", create=True, side_effect=OSError)
    def test_missing_apis_are_safe(self, dll):
        window_chrome.configure_title_bar(123)
        window_chrome.set_app_id()
        self.assertEqual(dll.call_count, 2)

    @patch("window_chrome.sys.platform", "linux")
    @patch("window_chrome.ctypes.WinDLL", create=True)
    def test_other_platforms_do_nothing(self, dll):
        window_chrome.configure_title_bar(123)
        window_chrome.set_app_id()
        dll.assert_not_called()

    @patch("window_chrome.sys.platform", "win32")
    @patch("window_chrome.ctypes.WinDLL", create=True)
    def test_app_id(self, dll):
        window_chrome.set_app_id()
        dll.return_value.SetCurrentProcessExplicitAppUserModelID.assert_called_once_with("OmniPDF.Editor")

    @patch('window_chrome.sys.platform', 'win32')
    @patch('window_chrome.ctypes.WinDLL', create=True)
    def test_update_mutex_is_held_until_released(self, dll):
        dll.return_value.CreateMutexW.return_value = 123
        handle = window_chrome.create_app_mutex()
        self.assertEqual(handle, 123)
        dll.return_value.CreateMutexW.assert_called_once_with(None, False, 'OmniPDF.App')
        window_chrome.release_app_mutex(handle)
        dll.return_value.CloseHandle.assert_called_once_with(123)


if __name__ == "__main__":
    unittest.main()
