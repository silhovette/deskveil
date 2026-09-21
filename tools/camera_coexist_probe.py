"""Two real camera clients, no saved or displayed images."""
import json
from pathlib import Path
import subprocess
import sys
import time


def client():
    import cv2
    cap = cv2.VideoCapture(0, cv2.CAP_MSMF)
    frames, times = 0, []
    try:
        if not cap.isOpened():
            print(json.dumps({"opened": False}), flush=True)
            return 2
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 360)
        cap.set(cv2.CAP_PROP_FPS, 30)
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline:
            start = time.monotonic()
            ok, frame = cap.read()
            elapsed = time.monotonic() - start
            if not ok:
                break
            frames += 1
            times.append(elapsed)
        print(json.dumps({"opened": True, "frames": frames,
                          "max_read": max(times, default=0),
                          "mean_read": sum(times) / max(1, len(times))}), flush=True)
        return 0 if frames >= 60 else 2
    finally:
        cap.release()


def main():
    commands = [sys.executable, str(Path(__file__).resolve()), "--client"]
    processes = [subprocess.Popen(commands, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                 for _ in range(2)]
    try:
        for index, process in enumerate(processes):
            out, err = process.communicate(timeout=35)
            print(f"Client {index + 1}: {out.strip()} (exit {process.returncode})")
            if err:
                print(err[-1200:])
        return int(any(p.returncode != 0 for p in processes))
    finally:
        for process in processes:
            if process.poll() is None:
                process.terminate()
                process.wait()


if __name__ == "__main__":
    sys.exit(client() if "--client" in sys.argv else main())
