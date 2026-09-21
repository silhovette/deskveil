"""Verify movement suppression and OS hook cleanup after abrupt app exit."""
import ctypes
from ctypes import wintypes
from pathlib import Path
import subprocess
import sys
import time
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def child():
    from PySide6.QtWidgets import QApplication
    from ui.native import CursorFreeze
    app = QApplication([])
    freeze = CursorFreeze()
    freeze.acquire()
    assert freeze.hook
    print("ready", flush=True)
    app.exec()


def main():
    api = ctypes.windll.user32
    original = wintypes.POINT()
    api.GetCursorPos(ctypes.byref(original))
    child_process = subprocess.Popen([sys.executable, __file__, "--child"], stdout=subprocess.PIPE, text=True)
    try:
        assert child_process.stdout.readline().strip() == "ready"
        api.mouse_event(1, -20 if original.x > 30 else 20, -20 if original.y > 30 else 20, 0, 0)
        time.sleep(.15)
        current = wintypes.POINT()
        api.GetCursorPos(ctypes.byref(current))
        assert (current.x, current.y) == (original.x, original.y)
        child_process.terminate()
        child_process.wait(5)
        api.mouse_event(1, -20 if original.x > 30 else 20, -20 if original.y > 30 else 20, 0, 0)
        time.sleep(.15)
        api.GetCursorPos(ctypes.byref(current))
        assert (current.x, current.y) != (original.x, original.y)
        print("PASS: covered mouse cannot move; abrupt process exit restores movement")
    finally:
        if child_process.poll() is None:
            child_process.terminate()
            child_process.wait(5)
        api.SetCursorPos(original.x, original.y)


if __name__ == "__main__":
    child() if "--child" in sys.argv else main()
