"""Apply native Windows window colors without changing the window frame."""

import ctypes
import sys


def configure_title_bar(hwnd: int) -> None:
    if sys.platform != "win32" or not hwnd:
        return
    try:
        set_attribute = ctypes.WinDLL("dwmapi").DwmSetWindowAttribute
        set_attribute.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_uint32]
        set_attribute.restype = ctypes.c_int32
        light = ctypes.c_int32(0)
        if set_attribute(hwnd, 20, ctypes.byref(light), ctypes.sizeof(light)) != 0:
            set_attribute(hwnd, 19, ctypes.byref(light), ctypes.sizeof(light))
        for attribute, color in ((34, 0xF1E4DB), (35, 0xFFFFFF), (36, 0x493426)):
            value = ctypes.c_uint32(color)
            set_attribute(hwnd, attribute, ctypes.byref(value), ctypes.sizeof(value))
    except (OSError, AttributeError):
        pass


def set_app_id() -> None:
    if sys.platform != "win32":
        return
    try:
        set_id = ctypes.WinDLL("shell32").SetCurrentProcessExplicitAppUserModelID
        set_id.argtypes = [ctypes.c_wchar_p]
        set_id.restype = ctypes.c_int32
        set_id("OmniPDF.Editor")
    except (OSError, AttributeError):
        pass


def create_app_mutex():
    if sys.platform != 'win32':
        return None
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
    kernel.CreateMutexW.restype = ctypes.c_void_p
    handle = kernel.CreateMutexW(None, False, 'OmniPDF.App')
    if not handle:
        raise OSError('Could not create the application update mutex.')
    return handle


def release_app_mutex(handle):
    if handle is not None and sys.platform == 'win32':
        kernel = ctypes.WinDLL('kernel32')
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel.CloseHandle.restype = ctypes.c_bool
        kernel.CloseHandle(handle)
