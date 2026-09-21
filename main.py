"""DeskVeil hides your screen. Windows Lock secures your computer."""
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import sys
import time
from PySide6.QtCore import QObject, QThread, QTimer, Signal, Qt
from PySide6.QtWidgets import QApplication, QMessageBox, QSystemTrayIcon
import config
from detection.camera_worker import CameraWorker
from detection.presence_engine import PresenceEngine, State, owner_candidate
from ui.camera_preview import CameraPreview
from ui.hotkey import EmergencyHotkey
from ui.tray import Tray
from ui.veil import VeilManager


def setup_logging():
    folder = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "DeskVeil" / "logs"
    try:
        folder.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(folder / "deskveil.log", maxBytes=262144,
                                      backupCount=2, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    except OSError:
        handler = logging.NullHandler()
    log = logging.getLogger("deskveil")
    log.setLevel(logging.INFO)
    log.addHandler(handler)


class Controller(QObject):
    monitoring = Signal(bool, int)
    preview_requested = Signal(bool)
    stopping = Signal()

    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.closing = False
        self.enabled = True
        self.generation = 0
        self.engine = PresenceEngine()
        self.camera_status = "Starting camera…"
        self.monitoring_since = time.monotonic()
        self.last_frame = None
        self.last_tray_status = None
        self.hotkey = EmergencyHotkey(app, self.snooze, self.reveal)
        self.veils = VeilManager(app)
        self.preview = CameraPreview()
        self.preview.closed.connect(lambda: self.preview_requested.emit(False))
        self.tray = Tray(self)
        self.tray.enabled_requested.connect(self.set_enabled)
        self.tray.cover_requested.connect(lambda: QTimer.singleShot(0, self.cover_now))
        self.tray.snooze_requested.connect(self.snooze)
        self.tray.resume_requested.connect(self.resume)
        self.tray.preview_requested.connect(self.open_preview)
        self.tray.exit_requested.connect(self.shutdown)
        self.thread = QThread(self)
        self.worker = CameraWorker()
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.initialize)
        self.monitoring.connect(self.worker.set_monitoring)
        self.preview_requested.connect(self.worker.set_preview)
        self.stopping.connect(self.worker.shutdown)
        self.worker.status_changed.connect(self.on_status)
        self.worker.finished.connect(self.worker.deleteLater)
        self.worker.finished.connect(self.thread.quit, Qt.ConnectionType.DirectConnection)
        self.thread.finished.connect(self.app.quit)
        self.timer = QTimer(self)
        self.timer.setInterval(50)
        self.timer.timeout.connect(self.poll)
        app.aboutToQuit.connect(self.finish_shutdown)
        self.thread.start()
        self.tray.show()
        self.start_monitoring(True)
        self.timer.start()

    def start_monitoring(self, enabled):
        self.generation += 1
        self.last_frame = None
        self.monitoring_since = time.monotonic()
        self.camera_status = "Starting camera…" if enabled else "Snoozed"
        self.preview.clear_frame(self.camera_status)
        self.monitoring.emit(enabled, self.generation)

    def on_status(self, text, generation):
        if not self.closing and generation == self.generation:
            self.camera_status = text
            if "unavailable" in text:
                self.engine.interrupt()
                self.preview.clear_frame(text)
            self.render()

    def poll(self):
        if self.closing:
            return
        if not self.enabled:
            self.worker.take_sample()
            self.worker.take_preview()
            self.render()
            return
        now = time.monotonic()
        was_snoozed = self.engine.state == State.SNOOZED
        self.engine.tick(now)
        if was_snoozed and self.engine.state != State.SNOOZED:
            self.start_monitoring(True)
        sample = self.worker.take_sample()
        if sample is not None and self.engine.state != State.SNOOZED:
            boxes, captured, generation = sample
            if generation == self.generation:
                if boxes is None or now - captured > config.MAX_SAMPLE_GAP:
                    self.engine.interrupt()
                else:
                    self.last_frame = captured
                    self.engine.update(owner_candidate(boxes), captured)
        frame = self.worker.take_preview()
        if frame is not None and self.preview.isVisible() and self.engine.state != State.SNOOZED:
            image, boxes, generation = frame
            if generation == self.generation:
                self.preview.set_frame(image, boxes)
        # No inference progress (including a blocked driver) is an unknown state.
        reference = self.last_frame if self.last_frame is not None else self.monitoring_since
        if self.engine.state != State.SNOOZED and now - reference > config.MAX_SAMPLE_GAP:
            self.engine.interrupt()
            if self.camera_status == "Camera ready":
                self.preview.clear_frame("Waiting for fresh camera data…")
        self.render()

    def render(self):
        self.hotkey.set_covered(self.engine.covered)
        if self.engine.covered and self.preview.isVisible():
            self.preview.close()
        self.veils.set_covered(self.engine.covered)
        now = time.monotonic()
        snoozed = self.engine.state == State.SNOOZED
        reference = self.last_frame if self.last_frame is not None else self.monitoring_since
        error = self.enabled and not snoozed and ("unavailable" in self.camera_status or
                                now - reference > config.MAX_SAMPLE_GAP)
        if not self.enabled:
            text = "Off"
        elif snoozed:
            remaining = max(0, int(self.engine.snoozed_until - now + .999))
            text = f"Snoozed · {remaining // 60}:{remaining % 60:02d}"
        elif error:
            text = self.camera_status if "unavailable" in self.camera_status else "Waiting for camera"
            if self.engine.covered:
                text += " · covered"
        elif self.engine.covered:
            text = "On · covered"
        else:
            text = "On" if self.last_frame is not None else "Starting…"
        status = text, snoozed, error, self.enabled
        if status != self.last_tray_status:
            # Record health transitions, not the changing snooze countdown.
            previous = self.last_tray_status
            if not snoozed and (previous is None or previous[2] != error):
                age = max(0., now - reference)
                logging.getLogger("deskveil").info("Monitoring health: %s (sample age %.2fs)", text, age)
            self.last_tray_status = status
            self.tray.set_status(*status)

    def set_enabled(self, enabled):
        if self.closing or self.enabled == enabled:
            return
        self.enabled = enabled
        self.engine.resume()
        self.preview.close()
        self.veils.set_covered(False, immediate=True)
        self.start_monitoring(enabled)
        self.render()

    def cover_now(self):
        if self.closing or not self.enabled:
            return
        self.engine.cover_now()
        self.preview.close()
        self.start_monitoring(True)
        self.render()

    def snooze(self):
        if self.closing or not self.enabled:
            return
        self.engine.snooze(time.monotonic(), config.SNOOZE_MINUTES * 60)
        # This runs on the UI thread; no camera/model operation is awaited.
        self.veils.set_covered(False, immediate=True)
        self.start_monitoring(False)
        self.render()

    def reveal(self):
        if self.closing or not self.engine.covered:
            return
        self.engine.resume()
        # Reset the observation boundary without stopping/releasing the camera.
        self.start_monitoring(True)
        self.veils.set_covered(False, immediate=True)
        self.render()

    def resume(self):
        if self.closing or not self.enabled:
            return
        self.engine.resume()
        self.start_monitoring(True)
        self.render()

    def open_preview(self):
        if self.closing or not self.enabled or self.engine.covered:
            return
        self.preview_requested.emit(True)
        self.preview.showNormal()
        if sys.platform == "win32":
            import ctypes
            hwnd = ctypes.c_void_p(int(self.preview.winId()))
            ctypes.windll.user32.ShowWindow(hwnd, 9)
            ctypes.windll.user32.SetForegroundWindow(hwnd)
        self.preview.raise_()
        self.preview.activateWindow()

    def shutdown(self):
        if self.closing:
            return
        self.closing = True
        self.timer.stop()
        self.veils.set_covered(False, immediate=True)
        self.preview.close()
        self.tray.hide()
        self.hotkey.close()
        self.stopping.emit()

    def finish_shutdown(self):
        self.shutdown()
        # Never terminate a native camera/inference thread while it owns resources.
        self.thread.wait()


def main():
    setup_logging()
    app = QApplication(sys.argv)
    app.setApplicationName("DeskVeil")
    app.setQuitOnLastWindowClosed(False)
    if sys.platform != "win32":
        QMessageBox.critical(None, "DeskVeil", "DeskVeil V1 supports Windows only.")
        return 1
    if not QSystemTrayIcon.isSystemTrayAvailable():
        QMessageBox.critical(None, "DeskVeil", "A Windows system tray is required.")
        return 1
    try:
        controller = Controller(app)
    except RuntimeError as error:
        QMessageBox.critical(None, "DeskVeil", str(error))
        return 1
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
