"""Native test: changing content behind the veil, focus and mouse suppression."""
import ctypes
from ctypes import wintypes
from pathlib import Path
import sys
import time
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QTimer
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QApplication, QWidget
from PySide6.QtCore import QEventLoop, QTimer
from ui.veil import VeilManager

def wait_events(milliseconds):
    # Use the real Qt event loop so capture/composition threads can acquire
    # Python's GIL between native operations (qWait can starve these threads).
    loop = QEventLoop()
    QTimer.singleShot(milliseconds, loop.quit)
    loop.exec()



class Animation(QWidget):
    def __init__(self):
        super().__init__()
        self.frames = 0
        self.inputs = 0
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.advance)
        self.timer.start(100)

    def advance(self):
        self.frames += 1
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor('red' if self.frames % 6 < 3 else 'blue'))

    def mousePressEvent(self, event):
        self.inputs += 1

    def wheelEvent(self, event):
        self.inputs += 1


def main():
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    animated = Animation()
    animated.setGeometry(app.primaryScreen().geometry())
    animated.show()
    animated.activateWindow()
    wait_events(250)
    api = ctypes.windll.user32
    api.GetForegroundWindow.restype = wintypes.HWND
    foreground = api.GetForegroundWindow()
    original = wintypes.POINT()
    api.GetCursorPos(ctypes.byref(original))
    manager = VeilManager(app)
    try:
        manager.set_covered(True, immediate=True)
        window = manager.windows[app.primaryScreen()]
        for _ in range(40):
            if window.isVisible():
                break
            wait_events(50)
        assert window.isVisible(), 'Initial asynchronous capture did not finish'
        assert window.live_capture, 'Capture exclusion unavailable'
        initial_frames = animated.frames
        colors = set()
        elapsed = []
        for _ in range(25):
            start = time.perf_counter()
            wait_events(50)
            elapsed.append(time.perf_counter() - start)
            pixel = window.background.pixelColor(window.background.width()//2, window.background.height()//2)
            colors.add('red' if pixel.red() > 180 and pixel.blue() < 60 else
                       'blue' if pixel.blue() > 180 and pixel.red() < 60 else 'other')
        assert {'red', 'blue'} <= colors, f'Underlying content not updating: {colors}'
        assert animated.frames > initial_frames + 5
        assert api.GetForegroundWindow() == foreground, f'Foreground changed: {foreground} -> {api.GetForegroundWindow()}, animation={int(animated.winId())}, veil={int(window.winId())}'
        api.mouse_event(1, 20, 20, 0, 0)
        api.mouse_event(2, 0, 0, 0, 0)
        api.mouse_event(4, 0, 0, 0, 0)
        api.mouse_event(0x800, 0, 0, 120, 0)
        wait_events(100)
        current = wintypes.POINT()
        api.GetCursorPos(ctypes.byref(current))
        assert (current.x, current.y) == (original.x, original.y)
        assert animated.inputs == 0
        print(f'PASS: live underlying red/blue frames, focus retained, mouse move/click/wheel blocked; max GUI wait {max(elapsed):.3f}s')
    finally:
        manager.set_covered(False, immediate=True)
        animated.close()
        for screen in list(manager.windows):
            manager.remove_screen(screen)
        app.processEvents()


if __name__ == '__main__':
    main()
