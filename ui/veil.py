"""Full-screen text-free frosted glass; mouse-blocking and non-activating."""
import sys
import time
from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QGuiApplication, QImage
from PySide6.QtWidgets import QWidget
import config
from ui.glass import frost
from ui.glass_compositor import GlassCompositor
from ui.native import CursorFreeze, cover_monitor, exclude_from_capture, available, monitor_bounds
from ui.live_glass import LiveGlass


class VeilWindow(QWidget):
    frame_ready = Signal()

    def __init__(self, screen):
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint |
                         Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setCursor(Qt.CursorShape.BlankCursor)
        self.setWindowTitle("DeskVeil")
        self.screen_ref = screen
        self.wanted = False
        self.background = QImage()
        self.surface = QImage()
        self.frame_ready.connect(self.refresh_background, Qt.ConnectionType.QueuedConnection)
        self.capture = LiveGlass(self.frame_ready.emit) if available() else None
        self.pending_cover = False
        self.pending_immediate = False
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        self.live_capture = False
        # A layered window below full alpha avoids marking underlying windows
        # as fully occluded (Chromium can otherwise stop producing video frames).
        self.cover_opacity = 254 / 255 if available() else 1.
        self.setGeometry(screen.geometry())
        self.animation = QTimer(self)
        self.animation.setInterval(16)
        self.animation.setTimerType(Qt.TimerType.PreciseTimer)
        self.animation.timeout.connect(self.advance_animation)
        self.fade_started = 0
        self.fade_from = 0.
        self.fade_to = 1.
        screen.geometryChanged.connect(self.reposition)

    def reposition(self, *_):
        self.setGeometry(self.screen_ref.geometry())
        if self.wanted:
            self.enforce_coverage()
            if self.capture:
                self.capture.start(monitor_bounds(int(self.winId())))

    def enforce_coverage(self):
        if self.wanted and self.isVisible():
            cover_monitor(int(self.winId()))

    def prepare_background(self):
        if self.capture:
            self.capture.start(monitor_bounds(int(self.winId())))
            return
        if not self.isVisible() and hasattr(self.screen_ref, "grabWindow"):
            self.background = frost(self.screen_ref.grabWindow(0).toImage())
            self.surface = GlassCompositor().compose(self.background, round(self.width()*self.devicePixelRatioF()),
                                                     round(self.height()*self.devicePixelRatioF()))

    def refresh_background(self):
        if self.capture:
            frame = self.capture.take()
            if frame is None:
                return
            if not frame.surface.isNull():
                self.background = frame.background
                self.surface = frame.surface
                self.update()
            if self.pending_cover:
                self.pending_cover = False
                self.show_cover(self.pending_immediate)
            if not self.live_capture:
                self.capture.stop()

    def set_covered(self, covered, immediate=False):
        self.wanted = covered
        self.animation.stop()
        if covered and not self.isVisible() and self.capture:
            self.pending_cover = True
            self.pending_immediate = immediate
            self.prepare_background()
            return
        if not covered:
            self.pending_cover = False
            if not self.isVisible():
                self.stop_capture()
        self.show_cover(immediate)

    def show_cover(self, immediate):
        covered = self.wanted
        if covered:
            if not self.isVisible():
                if self.background.isNull() and not self.capture:
                    self.prepare_background()
                self.setWindowOpacity(self.cover_opacity if immediate else 0.)
                self.reposition()
                self.show()
                self.raise_()
                self.enforce_coverage()
        if immediate:
            self.setWindowOpacity(self.cover_opacity if covered else 0.)
            if not covered:
                self.stop_capture()
                self.hide()
                self.background = QImage()
            return
        self.fade_from = self.windowOpacity()
        self.fade_to = self.cover_opacity if covered else 0.
        self.fade_started = time.monotonic()
        self.animation.start()

    def advance_animation(self):
        progress = min(1., (time.monotonic() - self.fade_started) * 1000 / max(1, config.VEIL_FADE_MS))
        self.setWindowOpacity(self.fade_from + (self.fade_to - self.fade_from) * progress)
        if progress >= 1.:
            self.animation.stop()
            self.finish_animation()

    def showEvent(self, event):
        super().showEvent(event)
        if sys.platform == "win32" and QGuiApplication.platformName() == "windows":
            import ctypes
            from ctypes import wintypes
            user32 = ctypes.windll.user32
            user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
            user32.GetWindowLongW.restype = ctypes.c_long
            user32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]
            user32.SetWindowLongW.restype = ctypes.c_long
            hwnd = int(self.winId())
            style = user32.GetWindowLongW(hwnd, -20)
            user32.SetWindowLongW(hwnd, -20, style | 0x08000000)  # WS_EX_NOACTIVATE
            user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
            user32.ShowWindow(hwnd, 4)  # SW_SHOWNOACTIVATE, including hidden VBS launches
            self.live_capture = exclude_from_capture(hwnd)
            if not self.live_capture:
                import logging
                logging.getLogger("deskveil").error("Live glass unavailable: capture exclusion failed; keeping static cover")

    def finish_animation(self):
        if not self.wanted:
            self.stop_capture()
            self.hide()
            self.background = QImage()

    def stop_capture(self):
        if self.capture:
            self.capture.stop()
        self.background = QImage()
        self.surface = QImage()

    def shutdown(self):
        self.animation.stop()
        self.stop_capture()
        if self.capture:
            self.capture.close()
            self.capture = None

    def paintEvent(self, event):
        painter = QPainter(self)
        if not self.surface.isNull():
            painter.drawImage(self.rect(), self.surface)
        else:
            painter.fillRect(self.rect(), QColor("#273346"))

    def closeEvent(self, event):
        event.ignore()


class VeilManager(QObject):
    def __init__(self, app, window_factory=VeilWindow):
        super().__init__(app)
        self.windows = {}
        self.covered = False
        self.window_factory = window_factory
        self.cursor = CursorFreeze()
        self.cover_timer = QTimer(self)
        self.cover_timer.setInterval(200)
        self.cover_timer.timeout.connect(self.maintain_cover)
        if hasattr(app, "aboutToQuit"):
            app.aboutToQuit.connect(self.cursor.release)
            app.aboutToQuit.connect(self.shutdown)
        for screen in app.screens():
            self.add_screen(screen)
        app.screenAdded.connect(self.add_screen)
        app.screenRemoved.connect(self.remove_screen)

    def maintain_cover(self):
        if self.covered:
            for window in self.windows.values():
                window.enforce_coverage()
            self.cursor.hide_pointer()

    def add_screen(self, screen):
        if screen not in self.windows:
            window = self.window_factory(screen)
            self.windows[screen] = window
            if self.covered:
                window.set_covered(True, immediate=True)

    def remove_screen(self, screen):
        window = self.windows.pop(screen, None)
        if window is not None:
            window.set_covered(False, immediate=True)
            window.shutdown()
            window.deleteLater()

    def shutdown(self):
        self.cover_timer.stop()
        self.cursor.release()
        for window in self.windows.values():
            window.shutdown()

    def set_covered(self, covered, immediate=False):
        if self.covered == covered and not immediate:
            return
        self.covered = covered
        if not covered:
            self.cover_timer.stop()
            self.cursor.release()
        if covered:
            # Capture every monitor before showing any cover window.
            for window in self.windows.values():
                window.prepare_background()
        for window in self.windows.values():
            window.set_covered(covered, immediate)
        if covered:
            self.cursor.acquire()
            self.cover_timer.start()
