"""Read/infer briefly on the real camera; do not display or save any images."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import time
import cv2
import config
from detection.face_detector import FaceDetector


def main():
    cv2.setNumThreads(1)
    detector = FaceDetector()
    camera = cv2.VideoCapture(config.CAMERA_INDEX, cv2.CAP_DSHOW)
    try:
        if not camera.isOpened():
            print("Camera unavailable; hardware inference not verified.")
            return 2
        camera.set(cv2.CAP_PROP_FRAME_WIDTH, config.FRAME_WIDTH)
        camera.set(cv2.CAP_PROP_FRAME_HEIGHT, config.FRAME_HEIGHT)
        durations = []
        for _ in range(10):
            ok, frame = camera.read()
            if not ok:
                print("Camera read failed; hardware inference not verified.")
                return 2
            h, w = frame.shape[:2]
            scale = min(1., config.FRAME_WIDTH / w, config.FRAME_HEIGHT / h)
            if scale < 1:
                frame = cv2.resize(frame, (round(w * scale), round(h * scale)))
            start = time.monotonic()
            detector.detect(frame, start)
            durations.append(time.monotonic() - start)
            time.sleep(.2)
        print(f"Real camera/model: 10 inferences passed; mean {1000 * sum(durations) / len(durations):.1f} ms.")
        return 0
    finally:
        camera.release()
        detector.close()


if __name__ == "__main__":
    sys.exit(main())
