"""Full monitor coverage and a mouse-only hook removed with its process."""
import atexit
import ctypes
from ctypes import wintypes
import sys
from PySide6.QtGui import QGuiApplication


def available():
    return sys.platform == "win32" and QGuiApplication.platformName() == "windows"


def exclude_from_capture(hwnd):
    if not available():
        return False
    api = ctypes.windll.user32
    api.SetWindowDisplayAffinity.argtypes = [wintypes.HWND, wintypes.DWORD]
    return bool(api.SetWindowDisplayAffinity(hwnd, 0x11))


class MonitorInfo(ctypes.Structure):
    _fields_ = [("size", wintypes.DWORD), ("monitor", wintypes.RECT),
                ("work", wintypes.RECT), ("flags", wintypes.DWORD)]


def monitor_bounds(hwnd):
    if not available():
        return None
    api = ctypes.windll.user32
    api.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
    api.MonitorFromWindow.restype = wintypes.HANDLE
    api.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(MonitorInfo)]
    monitor = api.MonitorFromWindow(hwnd, 2)
    info = MonitorInfo()
    info.size = ctypes.sizeof(info)
    if api.GetMonitorInfoW(monitor, ctypes.byref(info)):
        r = info.monitor  # Full physical monitor bounds, including the taskbar.
        return r.left, r.top, r.right-r.left, r.bottom-r.top


def cover_monitor(hwnd):
    bounds = monitor_bounds(hwnd)
    if bounds:
        api = ctypes.windll.user32
        api.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                    ctypes.c_int, ctypes.c_int, wintypes.UINT]
        api.SetWindowPos(hwnd, -1, *bounds, 0x0010 | 0x0040)


class CursorFreeze:
    def __init__(self):
        self.hook = None
        self.callback = None
        self.previous_cursor = None
        atexit.register(self.release)

    def acquire(self):
        if not available() or self.hook is not None:
            return
        api = ctypes.windll.user32
        callback_type = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
        api.SetWindowsHookExW.argtypes = [ctypes.c_int, callback_type, wintypes.HINSTANCE, wintypes.DWORD]
        api.SetWindowsHookExW.restype = wintypes.HANDLE
        api.CallNextHookEx.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
        api.CallNextHookEx.restype = ctypes.c_ssize_t
        kernel = ctypes.windll.kernel32
        kernel.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
        kernel.GetModuleHandleW.restype = wintypes.HMODULE

        def block(code, message, data):
            return 1 if code >= 0 else api.CallNextHookEx(None, code, message, data)

        self.callback = callback_type(block)
        self.hook = api.SetWindowsHookExW(14, self.callback, kernel.GetModuleHandleW(None), 0) or None
        if self.hook is None:
            import logging
            logging.getLogger("deskveil").error("Could not install mouse hook")
        api.GetCursor.restype = wintypes.HANDLE
        self.previous_cursor = api.GetCursor()
        self.hide_pointer()

    def hide_pointer(self):
        if available():
            # Blocked mouse movement prevents WM_SETCURSOR from reaching the
            # veil, so Qt's BlankCursor alone can leave the old pointer visible.
            api = ctypes.windll.user32
            api.SetCursor.argtypes = [wintypes.HANDLE]
            api.SetCursor.restype = wintypes.HANDLE
            class CursorInfo(ctypes.Structure):
                _fields_ = [("size", wintypes.DWORD), ("flags", wintypes.DWORD),
                            ("cursor", wintypes.HANDLE), ("position", wintypes.POINT)]
            info = CursorInfo()
            info.size = ctypes.sizeof(info)
            if api.GetCursorInfo(ctypes.byref(info)) and not info.flags & 1:
                return
            # The veil never takes focus. A layered veil may leave the cursor
            # owned by the foreground input queue; briefly share that queue
            # to change its cursor, without activating any window.
            api.GetForegroundWindow.restype = wintypes.HWND
            api.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
            current = ctypes.windll.kernel32.GetCurrentThreadId()
            foreground = api.GetWindowThreadProcessId(api.GetForegroundWindow(), None)
            attached = foreground != current and api.AttachThreadInput(current, foreground, True)
            try:
                api.SetCursor(None)
            finally:
                if attached:
                    api.AttachThreadInput(current, foreground, False)

    def release(self):
        if self.hook is not None:
            api = ctypes.windll.user32
            api.UnhookWindowsHookEx.argtypes = [wintypes.HANDLE]
            api.UnhookWindowsHookEx(self.hook)
            self.hook = None
            self.callback = None
        if available():
            api = ctypes.windll.user32
            api.LoadCursorW.argtypes = [wintypes.HINSTANCE, ctypes.c_void_p]
            api.LoadCursorW.restype = wintypes.HANDLE
            api.SetCursor.argtypes = [wintypes.HANDLE]
            api.SetCursor.restype = wintypes.HANDLE
            api.SetCursor(self.previous_cursor or api.LoadCursorW(None, 32512))
            self.previous_cursor = None
