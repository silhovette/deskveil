"""Measure real cover transitions and UI latency, without saving desktop frames."""
from pathlib import Path
import sys
import time
import statistics
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QApplication, QWidget
from PySide6.QtGui import QPainter, QColor
from ui.veil import VeilWindow, VeilManager

measurements = {name: [] for name in ('prepare', 'refresh', 'paint', 'animation_gap', 'heartbeat')}


def measured(name, function, *args):
    start = time.perf_counter()
    result = function(*args)
    measurements[name].append((time.perf_counter() - start) * 1000)
    return result


class Window(VeilWindow):
    last_animation = None

    def __init__(self, screen):
        super().__init__(screen)
        self.reference_poll = None
        if '--reference' in sys.argv and self.capture:
            self.capture.notify = None
            self.reference_poll = QTimer(self)
            self.reference_poll.setInterval(8)
            self.reference_poll.setTimerType(Qt.TimerType.PreciseTimer)
            self.reference_poll.timeout.connect(self.refresh_background)

    def set_covered(self, covered, immediate=False):
        self.last_animation = None
        super().set_covered(covered, immediate)

    def prepare_background(self):
        if self.reference_poll:
            self.reference_poll.start()
        return measured('prepare', super().prepare_background)

    def stop_capture(self):
        if self.reference_poll:
            self.reference_poll.stop()
        super().stop_capture()

    def refresh_background(self):
        return measured('refresh', super().refresh_background)

    def paintEvent(self, event):
        return measured('paint', super().paintEvent, event)

    def advance_animation(self):
        now = time.perf_counter()
        if self.last_animation and (now - self.last_animation) < .5:
            measurements['animation_gap'].append((now - self.last_animation) * 1000)
        self.last_animation = now
        super().advance_animation()


def main():
    if '--reference' in sys.argv:
        from glass_compute_benchmark import reference_downsample, reference_blur
        import ui.live_glass
        ui.live_glass.downsample = reference_downsample
        ui.live_glass.blur_small = reference_blur
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    content = None
    if '--synthetic' in sys.argv:
        class Content(QWidget):
            frame = 0

            def paintEvent(self, event):
                painter = QPainter(self)
                painter.fillRect(self.rect(), QColor(25 + self.frame % 70, 50, 90))

            def advance(self):
                self.frame += 1
                self.update()

        content = Content()
        content.showFullScreen()
        if '--dynamic' in sys.argv:
            changes = QTimer(content)
            changes.setInterval(33)
            changes.timeout.connect(content.advance)
            changes.start()
    manager = VeilManager(app, window_factory=Window)
    heartbeat = QTimer()
    heartbeat.setTimerType(Qt.TimerType.PreciseTimer)
    heartbeat.setInterval(8)
    previous = time.perf_counter()

    def tick():
        nonlocal previous
        now = time.perf_counter()
        measurements['heartbeat'].append((now - previous) * 1000)
        previous = now

    heartbeat.timeout.connect(tick)
    heartbeat.start()
    for start in (100, 1700, 3300):
        QTimer.singleShot(start, lambda: manager.set_covered(True))
        QTimer.singleShot(start + 1100, lambda: manager.set_covered(False))
    QTimer.singleShot(5000, app.quit)
    cpu = time.process_time()
    wall = time.perf_counter()
    try:
        app.exec()
    finally:
        manager.set_covered(False, immediate=True)
        if hasattr(manager, 'shutdown'):
            manager.shutdown()
        if content:
            content.close()
    print(f'CPU seconds={time.process_time()-cpu:.3f}, wall seconds={time.perf_counter()-wall:.3f}')
    for name, values in measurements.items():
        if values:
            values.sort()
            print(f'{name}: count={len(values)}, median={statistics.median(values):.2f}ms, p95={values[int((len(values)-1)*.95)]:.2f}ms, max={max(values):.2f}ms')


if __name__ == '__main__':
    main()
