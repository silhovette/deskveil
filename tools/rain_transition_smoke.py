"""Sample presented Windows pixels through Rain transitions over a synthetic scene.

No camera or desktop capture runs. Only this synthetic test window opts out of
capture exclusion so the screen sampler can inspect its actual presentation.
"""
import ctypes
from ctypes import wintypes
import json
from pathlib import Path
import sys
import threading
import time
from unittest.mock import patch
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QColor, QPainter
from PySide6.QtWidgets import QApplication, QWidget
from ui.veil import VeilWindow
from tools.live_glass_smoke import wait_events


class Scene(QWidget):
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(180, 190, 200))


def run():
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    screen = app.primaryScreen()
    scene = Scene(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
    scene.setGeometry(screen.geometry())
    scene.show()
    wait_events(250)
    api = ctypes.windll.user32
    api.GetDC.argtypes = [wintypes.HWND]
    api.GetDC.restype = wintypes.HDC
    api.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
    gdi = ctypes.windll.gdi32
    gdi.GetPixel.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
    gdi.GetPixel.restype = wintypes.DWORD
    phase = 'setup'
    samples = []
    done = threading.Event()
    point = screen.geometry().center()*screen.devicePixelRatio()

    def sample():
        dc = api.GetDC(None)
        try:
            while not done.is_set():
                pixel = gdi.GetPixel(dc, point.x(), point.y())
                samples.append((phase, time.perf_counter(), pixel & 255,
                                (pixel>>8)&255, (pixel>>16)&255))
                done.wait(.004)
        finally:
            api.ReleaseDC(None, dc)

    thread = threading.Thread(target=sample)
    thread.start()
    with patch('ui.veil.available', return_value=False), patch('ui.veil.exclude_from_capture', return_value=True):
        window = VeilWindow(screen)
        window.cover_opacity = 254/255
        def prepare():
            surface = QImage(round(window.width()*window.devicePixelRatioF()),
                             round(window.height()*window.devicePixelRatioF()), QImage.Format.Format_RGBA8888)
            surface.fill(QColor(90, 110, 130))
            pixels = np.frombuffer(surface.bits(), np.uint8).reshape(surface.height(), surface.width(), 4)
            pixels[:, :, 0] += ((np.arange(surface.width()) % 97)//6).astype(np.uint8)
            pixels[:, :, 1] += ((np.arange(surface.height()) % 91)//6).astype(np.uint8)[:, None]
            window.background = surface
            window.surface = surface
        window.prepare_background = prepare
        timings = {}
        try:
            for label, action in [('enable-hidden', lambda: window.set_rain_enabled(True)),
                                  ('cover-first', lambda: window.set_covered(True)),
                                  ('reveal-first', lambda: window.set_covered(False)),
                                  ('cover-again', lambda: window.set_covered(True)),
                                  ('rain-off-covered', lambda: window.set_rain_enabled(False)),
                                  ('rain-on-covered', lambda: window.set_rain_enabled(True)),
                                  ('reveal-immediate', lambda: window.set_covered(False, immediate=True))]:
                phase = label
                start = time.perf_counter()
                action()
                timings[label] = round((time.perf_counter()-start)*1000, 2)
                wait_events(650)
                if window.isVisible() and window.rain.active:
                    client = wintypes.RECT()
                    api.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
                    assert api.GetClientRect(int(window.rain.winId()), ctypes.byref(client))
                    assert client.right > window.surface.width() and client.bottom > window.surface.height(), \
                        ('GPU swapchain must extend beyond the clipped parent', client.right, client.bottom)
            phase = 'pixel-mapping'
            window.set_covered(True, immediate=True)
            wait_events(150)
            window.rain.timer.stop()
            window.rain.simulation.drops.clear()
            window.rain.simulation.trails.clear()
            window.rain.water_enabled = False
            window.rain.makeCurrent()
            window.rain.paintGL()
            frame = window.rain.grabFramebuffer().copy(0, 0, window.surface.width(), window.surface.height())
            window.rain.doneCurrent()
            frame = frame.convertToFormat(QImage.Format.Format_RGBA8888)
            actual = np.frombuffer(frame.constBits(), np.uint8).astype(np.int16)
            expected = np.frombuffer(window.surface.constBits(), np.uint8).astype(np.int16)
            error = int(np.abs(actual-expected).max())
            assert error <= 1, ('Enlarged GPU child must not scale or distort the frosted image', error)
            print('Processed background pixel error:', error)
        finally:
            phase = 'cleanup'
            window.set_covered(False, immediate=True)
            window.shutdown()
            scene.hide()
            done.set()
            thread.join()
        summary = {}
        for label in timings:
            pixels = [s for s in samples if s[0] == label]
            summary[label] = {'call_ms':timings[label], 'samples':len(pixels),
                              'minimum_rgb':min((s[2:] for s in pixels), default=None),
                              'fade_levels':len(set(s[2] for s in pixels if 100 < s[2] < 175)),
                              # Rain intentionally dims the background; detect empty/black frames.
                              'dark_frames':sum(max(s[2:]) < 55 for s in pixels)}
        print(json.dumps(summary, indent=2))
        assert all(s['dark_frames'] == 0 for s in summary.values()), 'Black/empty frame was presented'
        assert all(s['samples'] >= 20 for s in summary.values()), 'Presentation stalled during transitions'
        assert all(summary[phase]['fade_levels'] >= 3
                   for phase in ('cover-first', 'cover-again', 'reveal-first')), \
            'Veil transition must still fade rather than switch abruptly'


if __name__ == '__main__':
    run()
