import threading
import unittest
from unittest.mock import patch
from PySide6.QtGui import QImage
from ui.live_glass import LiveGlass


class LiveGlassTests(unittest.TestCase):
    def test_late_capture_is_discarded_after_reveal(self):
        entered, release, closed = threading.Event(), threading.Event(), threading.Event()

        class Capture:
            def __init__(self, bounds):
                pass

            def read(self):
                entered.set()
                release.wait(3)
                image = QImage(32, 32, QImage.Format.Format_RGB32)
                image.fill(0xff123456)
                return image

            def close(self):
                closed.set()

        with patch('ui.live_glass.DesktopCapture', Capture):
            worker = LiveGlass()
            try:
                worker.start((0, 0, 32, 32))
                self.assertTrue(entered.wait(3))
                worker.stop()
                release.set()
                self.assertTrue(closed.wait(3))
                self.assertIsNone(worker.take())
            finally:
                release.set()
                worker.close()

    def test_identical_frame_does_not_erase_unconsumed_result(self):
        entered, release = threading.Event(), threading.Event()
        notifications = []

        class Capture:
            def __init__(self, bounds):
                self.count = 0

            def read(self):
                self.count += 1
                if self.count == 3:
                    entered.set()
                    release.wait(3)
                image = QImage(32, 32, QImage.Format.Format_RGB32)
                image.fill(0xff123456)
                return image

            def close(self):
                pass

        with patch('ui.live_glass.DesktopCapture', Capture):
            worker = LiveGlass(lambda: notifications.append(True))
            try:
                worker.start((0, 0, 32, 32))
                self.assertTrue(entered.wait(3))
                self.assertEqual(len(notifications), 1)
                completed = worker.take()
                self.assertIsNotNone(completed)
                self.assertFalse(completed.surface.isNull())
                self.assertIsNone(worker.take())
            finally:
                release.set()
                worker.close()
