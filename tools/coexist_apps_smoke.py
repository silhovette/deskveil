"""Run the two packaged apps together and verify producer handover both ways."""
import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import subprocess
import sys
import time
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from detection.shared_camera import SharedCamera

ROOT = Path(__file__).resolve().parents[1]
api = ctypes.windll.user32
api.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
api.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]


def threads(process):
    ids = set()
    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def visit(hwnd, _):
        pid = wintypes.DWORD()
        thread = api.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value == process.pid:
            ids.add(thread)
        return True
    api.EnumWindows(visit, 0)
    return ids


def quit_app(process):
    if process.poll() is not None:
        return
    for thread in threads(process):
        api.PostThreadMessageW(thread, 0x0012, 0, 0)
    process.wait(15)
    assert process.returncode == 0


def main():
    processes = []
    deskveil = None
    local = Path(os.environ["LOCALAPPDATA"])
    peer_log = local / "peeker/logs/peeker.log"
    veil_log = local / "DeskVeil/logs/deskveil.log"

    def read(log, offset):
        if not log.exists():
            return ""
        with log.open("rb") as stream:
            stream.seek(offset)
            return stream.read().decode("utf-8", errors="replace")

    def start(path, log):
        offset = log.stat().st_size if log.exists() else 0
        process = subprocess.Popen([str(path)], cwd=path.parent)
        processes.append(process)
        return process, offset

    def reveal_if_covered():
        if deskveil is not None and deskveil.poll() is None:
            for thread in threads(deskveil):
                api.PostThreadMessageW(thread, 0x0312, 0x4457, 0)

    def wait_ready(process, log, offset, message):
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline:
            assert process.poll() is None
            reveal_if_covered()
            if message in read(log, offset):
                return
            time.sleep(.2)
        raise AssertionError(read(log, offset))

    def confirm_stream():
        camera = SharedCamera()
        count = 0
        try:
            started = time.monotonic()
            deadline = started + 12
            while (count < 50 or time.monotonic() - started < 6) and time.monotonic() < deadline:
                reveal_if_covered()
                ok, frame = camera.read()
                assert not camera.producer, "Neither app owns the camera"
                if ok and time.monotonic() - camera.timestamp < .35:
                    count += 1
            assert count >= 50, count
        finally:
            camera.release()

    try:
        peeker, peer_offset = start(ROOT.parent / "peeker/dist/peeker/peeker.exe", peer_log)
        wait_ready(peeker, peer_log, peer_offset, "camera started")
        deskveil, veil_offset = start(ROOT / "dist/DeskVeil/DeskVeil.exe", veil_log)
        wait_ready(deskveil, veil_log, veil_offset, "Camera ready")
        confirm_stream()
        running = read(veil_log, veil_offset).split("Camera ready", 1)[1]
        assert "unavailable" not in running and "Waiting for camera" not in running, running
        print("PASS: both packaged apps infer using one shared camera", flush=True)
        quit_app(peeker)
        time.sleep(2)
        confirm_stream()
        print("PASS: DeskVeil continues after peeker exits", flush=True)
        peeker, peer_offset = start(ROOT.parent / "peeker/dist/peeker/peeker.exe", peer_log)
        wait_ready(peeker, peer_log, peer_offset, "camera started")
        quit_app(deskveil)
        time.sleep(2)
        confirm_stream()
        print("PASS: restarted peeker continues after DeskVeil exits", flush=True)
    finally:
        for process in reversed(processes):
            try:
                quit_app(process)
            except subprocess.TimeoutExpired:
                process.terminate()
                process.wait(5)
                raise AssertionError("Application failed normal shutdown")


if __name__ == "__main__":
    main()
