"""Windows-only build check: starts the EXE and requests normal Qt shutdown.

Opens the real configured camera, processes locally, and never stores a frame.
"""
import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import subprocess
import time


def main():
    root = Path(__file__).resolve().parents[1]
    executable = root / "dist" / "DeskVeil" / "DeskVeil.exe"
    log = Path(os.environ["LOCALAPPDATA"]) / "DeskVeil" / "logs" / "deskveil.log"
    offset = log.stat().st_size if log.exists() else 0
    user32 = ctypes.windll.user32
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    process = subprocess.Popen([str(executable)], cwd=root)
    threads = set()

    @callback_type
    def visit(hwnd, _):
        pid = wintypes.DWORD()
        thread = user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value == process.pid:
            threads.add(thread)
        return True

    try:
        deadline = time.monotonic() + 30
        status = ""
        while time.monotonic() < deadline:
            assert process.poll() is None, f"EXE exited early: {process.returncode}"
            if log.exists():
                with log.open("rb") as stream:
                    stream.seek(offset)
                    status = stream.read().decode("utf-8")
                if "Camera ready" in status:
                    break
            time.sleep(.2)
        assert "Camera ready" in status, f"No successful camera start: {status}"
        # A single frame is not enough: exercise sustained background capture.
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline:
            assert process.poll() is None, f"EXE exited early: {process.returncode}"
            with log.open("rb") as stream:
                stream.seek(offset)
                status = stream.read().decode("utf-8")
            running = status.split("Camera ready", 1)[1]
            assert "unavailable" not in running and "Waiting for camera" not in running, running
            time.sleep(.2)
        user32.EnumWindows(visit, 0)
        assert threads, "No Qt GUI thread found"
        for thread in threads:
            user32.PostThreadMessageW(thread, 0x0312, 0x4456, 0)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            with log.open("rb") as stream:
                stream.seek(offset)
                status = stream.read().decode("utf-8")
            if "Camera released" in status:
                break
            time.sleep(.2)
        assert "Camera released" in status, "Emergency shortcut did not snooze/release camera"
        with log.open("rb") as stream:
            stream.seek(offset)
            status = stream.read().decode("utf-8")
        assert "unavailable" not in status and "failure" not in status, status
        print("PASS: frozen EXE sustained camera monitoring for 12 seconds, emergency shortcut released camera")
    finally:
        user32.EnumWindows(visit, 0)
        for thread in threads:
            # WM_QUIT -> Qt application quit -> aboutToQuit resource cleanup.
            user32.PostThreadMessageW(thread, 0x0012, 0, 0)
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            process.terminate()
            process.wait(timeout=5)
            raise AssertionError("EXE failed graceful shutdown")
    assert process.returncode == 0, process.returncode
    print("PASS: frozen EXE normal shutdown; process exited with code 0")


if __name__ == "__main__":
    main()

