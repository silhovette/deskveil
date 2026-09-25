"""Play a generated video underneath live glass; no personal content saved."""
from pathlib import Path
import sys
import tempfile
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import cv2
import numpy as np
from PySide6.QtCore import QUrl
from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QEventLoop, QTimer, QEvent
from ui.veil import VeilManager

def wait_events(milliseconds):
    # Use the real Qt event loop so capture/composition threads can acquire
    # Python's GIL between native operations (qWait can starve these threads).
    loop = QEventLoop()
    QTimer.singleShot(milliseconds, loop.quit)
    loop.exec()



def main():
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    with tempfile.TemporaryDirectory(prefix='deskveil-video-test-') as directory:
        path = str(Path(directory) / 'test.avi')
        writer = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*'MJPG'), 24, (640, 360))
        assert writer.isOpened()
        for index in range(240):
            frame = np.zeros((360, 640, 3), dtype=np.uint8)
            frame[:, :, 2 if (index // 12) % 2 == 0 else 0] = 255
            writer.write(frame)
        writer.release()
        video = QVideoWidget()
        video.setGeometry(app.primaryScreen().geometry())
        video.show()
        player = QMediaPlayer()
        player.setVideoOutput(video)
        player.setSource(QUrl.fromLocalFile(path))
        player.play()
        wait_events(700)
        manager = VeilManager(app)
        manager.set_rain_enabled('--rain' in sys.argv)
        try:
            assert player.playbackState() == QMediaPlayer.PlaybackState.PlayingState, player.errorString()
            before = player.position()
            manager.set_covered(True, immediate=True)
            window = manager.windows[app.primaryScreen()]
            colors = set()
            for _ in range(30):
                wait_events(80)
                pixel = window.background.pixelColor(window.background.width()//2, window.background.height()//2)
                if pixel.red() > 180 and pixel.blue() < 60:
                    colors.add('red')
                if pixel.blue() > 180 and pixel.red() < 60:
                    colors.add('blue')
            assert colors == {'red', 'blue'}, colors
            assert player.position() > before + 1500
            assert player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
            print('PASS: actual video playback and changing video frames continue underneath live glass')
        finally:
            manager.set_covered(False, immediate=True)
            player.stop()
            player.setSource(QUrl())
            video.close()
            for screen in list(manager.windows):
                manager.remove_screen(screen)
            app.processEvents()
            # This script uses nested loops instead of app.exec(). Drain the
            # deferred window/container destruction before QApplication dies.
            app.sendPostedEvents(None, QEvent.Type.DeferredDelete)


if __name__ == '__main__':
    main()
