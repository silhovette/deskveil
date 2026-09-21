"""Camera/model ownership stays on a QThread; latest-frame mailboxes stay bounded."""
import logging
import time
from threading import Lock
import cv2
from PySide6.QtCore import QObject, QTimer, Signal, Slot
from PySide6.QtGui import QImage
import config
from detection.face_detector import FaceDetector
from detection.shared_camera import SharedCamera


class CameraWorker(QObject):
    status_changed = Signal(str, int)
    finished = Signal()

    def __init__(self):
        super().__init__()
        self.camera = self.detector = self.timer = None
        self.enabled = self.preview_enabled = False
        self.generation = 0
        self.next_retry = self.next_inference = 0
        self.last_status = None
        self.warming_up = False
        self.lock = Lock()
        self.sample = self.preview = None

    def take_sample(self):
        with self.lock:
            sample, self.sample = self.sample, None
        return sample

    def take_preview(self):
        with self.lock:
            preview, self.preview = self.preview, None
        return preview

    @Slot()
    def initialize(self):
        cv2.setNumThreads(1)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.tick)

    def status(self, text):
        if text != self.last_status:
            self.last_status = text
            self.status_changed.emit(text, self.generation)
            logging.getLogger("deskveil").info(text)

    @Slot(bool)
    def set_preview(self, enabled):
        self.preview_enabled = enabled
        with self.lock:
            self.preview = None

    @Slot(bool, int)
    def set_monitoring(self, enabled, generation):
        self.enabled, self.generation = enabled, generation
        self.timer.stop()
        with self.lock:
            self.sample = self.preview = None
        self.last_status = None
        if enabled:
            self.next_retry = self.next_inference = 0
            self.status("Starting camera…")
            self.timer.start(0)
        else:
            self.release_camera()
            self.status("Camera released · snoozed")

    def release_camera(self):
        if self.camera is not None:
            self.camera.release()
            self.camera = None

    def unavailable(self, text):
        self.release_camera()
        with self.lock:
            self.sample = (None, time.monotonic(), self.generation)
            self.preview = None
        self.status(text)
        self.next_retry = time.monotonic() + config.CAMERA_RETRY_SECONDS

    @Slot()
    def tick(self):
        if not self.enabled:
            return
        start = time.monotonic()
        try:
            if start < self.next_retry:
                return
            if self.detector is None:
                if not config.MODEL_PATH.is_file():
                    self.unavailable("Model unavailable")
                    return
                self.detector = FaceDetector()
            if self.camera is None:
                self.camera = SharedCamera(config.CAMERA_INDEX)
                if not self.camera.isOpened():
                    self.unavailable("Camera unavailable")
                    return
                self.warming_up = True
            read_started = time.monotonic()
            ok, frame = self.camera.read()
            captured = time.monotonic()
            if not ok or frame is None:
                if self.camera.pending:
                    return  # Another client is opening/reopening the device.
                self.unavailable("Camera unavailable")
                return
            first_frame, self.warming_up = self.warming_up or self.camera.just_opened, False
            if captured - read_started > config.MAX_SAMPLE_GAP:
                if first_frame:
                    # Drivers can take seconds to produce their very first
                    # frame. Discard it, but let this open session warm up.
                    self.status("Camera warming up…")
                    return
                # A delayed driver read must not briefly advertise a healthy
                # stream. Reopen the stalled session instead of keeping it.
                self.unavailable("Camera unavailable (capture stalled)")
                return
            captured = self.camera.timestamp or captured
            if time.monotonic() - captured > config.MAX_SAMPLE_GAP:
                return
            if captured < self.next_inference:
                return
            height, width = frame.shape[:2]
            scale = min(1., config.FRAME_WIDTH / width, config.FRAME_HEIGHT / height)
            if scale < 1:
                frame = cv2.resize(frame, (round(width * scale), round(height * scale)))
            try:
                boxes = self.detector.detect(frame, captured)
            except Exception:
                # Recreate a failed native detector on the next retry.
                detector, self.detector = self.detector, None
                detector.close()
                raise
            with self.lock:
                self.sample = (tuple(boxes), captured, self.generation)
                if self.preview_enabled:
                    height, width = frame.shape[:2]
                    image = QImage(frame.data, width, height, frame.strides[0],
                                   QImage.Format.Format_BGR888).copy()
                    self.preview = (image, tuple(boxes), self.generation)
            self.status("Camera ready")
            self.next_inference = captured + 1 / config.INFERENCE_FPS
        except Exception as error:
            logging.getLogger("deskveil").error("Camera/detection failure (%s)", type(error).__name__)
            self.unavailable("Camera / detection unavailable")
        finally:
            if self.enabled:
                now = time.monotonic()
                # Drain the camera at capture cadence, infer only at 5 FPS.
                delay = max(1, round((1 / 30 - (now - start)) * 1000))
                if self.next_retry > now:
                    delay = max(1, round((self.next_retry - now) * 1000))
                self.timer.start(delay)

    @Slot()
    def shutdown(self):
        self.enabled = False
        if self.timer:
            self.timer.stop()
        try:
            self.release_camera()
            if self.detector:
                self.detector.close()
                self.detector = None
        finally:
            self.finished.emit()
