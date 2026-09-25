"""Native GPU checks for white mist, swept beads and gradual recovery."""
from pathlib import Path
import sys
import time
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
from PySide6.QtGui import QImage, QColor
from PySide6.QtWidgets import QApplication, QWidget
from ui.rain import RainWindow, PATTERN_SCALE
from ui.rain_simulation import Drop
from tools.live_glass_smoke import wait_events


def run():
    app = QApplication([])
    window = RainWindow(seed=23)
    host = QWidget()
    container = QWidget.createWindowContainer(window, host)
    host.resize(640, 480)
    container.setGeometry(host.rect())
    host.show()
    surface = QImage(round(host.width()*host.devicePixelRatioF()),
                     round(host.height()*host.devicePixelRatioF()), QImage.Format.Format_RGBA8888)
    surface.fill(QColor(80, 96, 112))
    window.start(surface)
    try:
        deadline = time.monotonic()+15
        while not window.presented:
            assert time.monotonic() < deadline and not window.broken
            wait_events(20)
        window.timer.stop()
        sim = window.simulation
        sim.drops.clear()
        sim.trails.clear()
        sim.layout.condensation = np.empty((0,10), np.float32)
        sim.static_revision += 1
        x,y = window.width()/2, window.height()/2

        def frame():
            window.makeCurrent()
            window.paintGL()
            result = window.grabFramebuffer().convertToFormat(QImage.Format.Format_RGBA8888)
            window.doneCurrent()
            return result

        original = frame()
        sim.add_trail(x,y-35,x,y+35,12,1,life=18,width_ratio=1)
        trail = sim.trails[0]
        px = round((x+10.5*PATTERN_SCALE)*window.devicePixelRatio())
        py = round(y*window.devicePixelRatio())
        levels = []
        for life in (18,14,8,4,.5):
            trail.life = life
            levels.append(frame().pixelColor(px,py).red())
        assert abs(levels[0]-80*.85) <= 1, levels
        assert all(a <= b for a,b in zip(levels,levels[1:])) and levels[-1] > levels[0], levels

        # Both kinds of static bead must be invisible in a fresh swept path,
        # but must contribute to the image again while that path recovers.
        trail.life = 18
        empty = frame()
        sim.drops = [Drop(x,y,2,7,1)]
        sim.layout.condensation = np.array([(x,y+15,1.5,1.5,1,0,7,0,1,0)], np.float32)
        sim.static_revision += 1
        assert frame() == empty, 'Static beads remained inside the cleared path'
        trail.life = 4
        recovering = frame()
        sim.drops.clear()
        sim.layout.condensation = np.empty((0,10), np.float32)
        sim.static_revision += 1
        assert frame() != recovering, 'Static beads did not fade back into the path'
        sim.trails.clear()
        assert frame() == original, 'White film did not fully recover'
        print(f'PASS: 98%-transparent white film; cleared red levels {levels}; '
              'static beads erased and restored; complete recovery matches original')
    finally:
        window.stop()
        window.cleanup()
        host.hide()


if __name__ == '__main__':
    run()
