"""Briefly cover the real displays, test the native hotkey message, then exit.

Uses a fake camera worker; no camera frames are captured. Run intentionally.
"""
import ctypes
from ctypes import wintypes
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import time
from unittest.mock import patch
from PySide6.QtCore import QObject, Signal, Slot, QTimer
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
import main
from detection.presence_engine import State


class FakeCamera(QObject):
    status_changed = Signal(str, int)
    finished = Signal()

    def __init__(self):
        super().__init__()
        self.sample = None

    @Slot()
    def initialize(self):
        pass

    @Slot(bool, int)
    def set_monitoring(self, enabled, generation):
        self.status_changed.emit("Camera ready" if enabled else "Snoozed", generation)

    @Slot(bool)
    def set_preview(self, enabled):
        pass

    def take_sample(self):
        sample, self.sample = self.sample, None
        return sample

    def take_preview(self):
        return None

    @Slot()
    def shutdown(self):
        self.finished.emit()


def run():
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    with patch.object(main, "CameraWorker", FakeCamera):
        controller = main.Controller(app)
    failures = []
    user32 = ctypes.windll.user32
    user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.GetWindowLongW.restype = ctypes.c_long
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.WindowFromPoint.argtypes = [wintypes.POINT]
    user32.WindowFromPoint.restype = wintypes.HWND
    user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
    user32.GetAncestor.restype = wintypes.HWND
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    thread_id = ctypes.windll.kernel32.GetCurrentThreadId()

    def checked(callback):
        def wrapped():
            try:
                callback()
            except Exception as error:
                import traceback
                traceback.print_exc()
                failures.append(repr(error))
                controller.shutdown()
        return wrapped

    def cover():
        controller.cover_now()
        assert controller.engine.covered
        QTimer.singleShot(500, checked(inspect_and_reveal))

    def inspect_and_reveal():
        assert len(controller.veils.windows) == len(app.screens())
        for screen, window in controller.veils.windows.items():
            assert not window.background.isNull(), "Glass background was not prepared"
            assert window.isVisible() and abs(window.windowOpacity() - window.cover_opacity) < .005, (screen.name(), window.isVisible(), window.windowOpacity(), controller.engine.state)
            assert window.geometry() == screen.geometry()
            assert user32.IsWindowVisible(int(window.winId())), "Native window hidden"
            style = user32.GetWindowLongW(int(window.winId()), -20)
            assert style & 0x08000000, "Missing WS_EX_NOACTIVATE"
            assert style & 0x00000008, "Missing WS_EX_TOPMOST"
            assert not style & 0x00000020, "Mouse clicks must not pass through"
            rect = wintypes.RECT()
            user32.GetWindowRect(int(window.winId()), ctypes.byref(rect))
            for point in (wintypes.POINT((rect.left + rect.right)//2, rect.bottom-2),
                          wintypes.POINT(rect.left+2, (rect.top + rect.bottom)//2)):
                top = user32.GetAncestor(user32.WindowFromPoint(point), 2)
                assert top == int(window.winId()), "Taskbar/another window is above the veil"
        original = wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(original))
        user32.mouse_event(0x0001, 20, 20, 0, 0)
        QTest.qWait(60)
        current = wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(current))
        assert (current.x, current.y) == (original.x, original.y), "Cursor was not frozen"
        class CursorInfo(ctypes.Structure):
            _fields_ = [("size", wintypes.DWORD), ("flags", wintypes.DWORD),
                        ("cursor", wintypes.HANDLE), ("position", wintypes.POINT)]
        info = CursorInfo()
        info.size = ctypes.sizeof(info)
        assert user32.GetCursorInfo(ctypes.byref(info))
        assert not info.flags & 1, "Cursor visible above the veil"
        assert controller.hotkey.reveal_registered
        assert user32.PostThreadMessageW(thread_id, 0x0312, controller.hotkey.REVEAL_ID, 0)
        QTimer.singleShot(250, checked(verify_quick_reveal))

    def verify_quick_reveal():
        assert controller.engine.state == State.PRESENT
        assert controller.engine.snoozed_until is None
        assert not controller.hotkey.reveal_registered
        assert controller.veils.cursor.hook is None, "Mouse hook not released"
        assert all(not w.isVisible() for w in controller.veils.windows.values())
        user32.GetCursor.restype = wintypes.HANDLE
        assert user32.GetCursor(), "Cursor not restored after reveal"
        class CursorInfo(ctypes.Structure):
            _fields_ = [("size", wintypes.DWORD), ("flags", wintypes.DWORD),
                        ("cursor", wintypes.HANDLE), ("position", wintypes.POINT)]
        info = CursorInfo()
        info.size = ctypes.sizeof(info)
        assert user32.GetCursorInfo(ctypes.byref(info)) and info.flags & 1, "Global pointer not restored"
        controller.cover_now()
        assert user32.PostThreadMessageW(thread_id, 0x0312, controller.hotkey.ID, 0)
        QTimer.singleShot(250, checked(verify_reveal))

    def verify_reveal():
        assert controller.engine.state == State.SNOOZED
        assert all(not w.isVisible() for w in controller.veils.windows.values())
        assert controller.engine.snoozed_until - time.monotonic() > 595
        controller.resume()
        controller.worker.sample = ((), time.monotonic(), controller.generation - 1)
        controller.poll()
        assert controller.engine.state == State.PRESENT, "Old camera sample accepted"
        controller.worker.sample = ((), time.monotonic() - 5, controller.generation)
        controller.poll()
        assert controller.engine.state == State.PRESENT, "Stale camera sample accepted"
        controller.cover_now()
        controller.tray.enabled_action.trigger()
        assert not controller.enabled
        assert not controller.engine.covered
        assert controller.veils.cursor.hook is None
        assert controller.tray.toolTip().startswith("DeskVeil · Paused")
        assert controller.tray.isVisible() and not controller.closing
        controller.worker.sample = ((), time.monotonic(), controller.generation)
        controller.poll()
        controller.cover_now()
        controller.snooze()
        assert not controller.engine.covered and not controller.enabled
        assert not controller.tray.cover_action.isEnabled()
        controller.tray.enabled_action.trigger()
        assert controller.enabled and controller.tray.cover_action.isEnabled()
        assert controller.engine.state == State.PRESENT
        controller.tray.on_activated(controller.tray.ActivationReason.Trigger)
        assert controller.tray.menu.isVisible(), "Left click did not open tray menu"
        assert controller.tray.contextMenu() == controller.tray.menu
        controller.tray.menu.hide()
        print(f"Native Windows smoke passed: {len(app.screens())} display(s), acrylic, window flags, Ctrl+V reveal without snooze, emergency reveal, stale samples, shutdown.")
        controller.shutdown()

    QTimer.singleShot(200, checked(cover))
    QTimer.singleShot(5000, checked(lambda: (_ for _ in ()).throw(RuntimeError("Smoke timeout"))))
    app.exec()
    if failures:
        print("FAILED:", failures)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(run())
