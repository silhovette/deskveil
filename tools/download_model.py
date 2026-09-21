"""Explicit installation step only. The application never downloads anything."""
from pathlib import Path
import urllib.request

URL = "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task"

if __name__ == "__main__":
    target = Path(__file__).resolve().parents[1] / "models" / "face_landmarker.task"
    target.parent.mkdir(exist_ok=True)
    if not target.exists():
        temporary = target.with_suffix(".download")
        try:
            urllib.request.urlretrieve(URL, temporary)
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)
    print(f"Model ready: {target}")
