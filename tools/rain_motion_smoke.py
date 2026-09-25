"""Verify motion in the actual layered veil, over a fixed synthetic backdrop."""
from pathlib import Path
import json
import sys
import time
from unittest.mock import patch
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QTimer
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication
from ui.veil import VeilWindow
from ui.rain import ANIMATION_SPEED
from tools.live_glass_smoke import wait_events


def run():
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    with patch('ui.veil.available', return_value=False):
        window = VeilWindow(app.primaryScreen())
    window.cover_opacity = 254/255

    def prepare():
        surface = QImage(round(window.width()*window.devicePixelRatioF()),
                         round(window.height()*window.devicePixelRatioF()), QImage.Format.Format_RGBA8888)
        surface.fill(QColor('#506070'))
        window.surface = window.background = surface

    window.prepare_background = prepare
    maintenance = QTimer()
    maintenance.setInterval(200)
    maintenance.timeout.connect(window.enforce_coverage)
    maintenance.start()
    try:
        window.set_rain_enabled(True)
        for cycle in range(2):
            window.set_covered(True)
            deadline = time.monotonic()+15
            while (not window.rain.presented or window.animation.isActive() or window.pending_rain_fade):
                assert time.monotonic() < deadline, 'Cover did not finish preparing'
                assert not window.rain.broken, 'Rain renderer failed'
                wait_events(20)
            rain = window.rain
            simulation = rain.simulation
            before = rain.grabFramebuffer().convertToFormat(QImage.Format.Format_RGBA8888)
            frames, clock, started = rain.frames, simulation.time, time.monotonic()
            wait_events(8000)
            elapsed = time.monotonic()-started
            advanced = simulation.time-clock
            after = rain.grabFramebuffer().convertToFormat(QImage.Format.Format_RGBA8888)
            a = np.frombuffer(before.constBits(), np.uint8).astype(np.int16)
            b = np.frombuffer(after.constBits(), np.uint8).astype(np.int16)
            changed = int(np.count_nonzero(np.max(np.abs(a-b).reshape(-1,4)[:,:3], axis=1) > 8))
            assert rain.timer.isActive(), 'Animation clock stopped while covered'
            assert advanced > elapsed*ANIMATION_SPEED*.75, 'Rain simulation clock stalled'
            assert changed > 1000, 'Presented rain remained static over a fixed background'
            print(json.dumps({'cycle':cycle+1, 'frames':rain.frames-frames,
                              'simulation_seconds':advanced, 'wall_seconds':elapsed,
                              'changed_pixels':changed}), flush=True)
            window.set_covered(False, immediate=True)
            stopped = rain.frames
            wait_events(150)
            assert rain.frames == stopped and not rain.timer.isActive()
    finally:
        maintenance.stop()
        window.set_covered(False, immediate=True)
        window.shutdown()
    print('PASS: first and repeated native covers animate; reveal stops animation')


if __name__ == '__main__':
    run()
