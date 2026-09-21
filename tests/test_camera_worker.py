import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import unittest
from unittest.mock import Mock, patch
import numpy as np
from PySide6.QtWidgets import QApplication
from detection.camera_worker import CameraWorker

app = QApplication.instance() or QApplication([])


class CameraTests(unittest.TestCase):
    def setUp(self):
        self.worker = CameraWorker()
        self.worker.initialize()
        self.worker.enabled = True
        self.worker.generation = 7
        self.worker.detector = Mock()
        self.camera = Mock()
        self.camera.pending = False
        self.camera.timestamp = None
        self.camera.just_opened = False
        self.worker.camera = self.camera

    def tearDown(self):
        self.worker.shutdown()

    def test_read_failure_is_unknown(self):
        self.camera.read.return_value = (False, None)
        self.worker.tick()
        boxes, _, generation = self.worker.take_sample()
        self.assertIsNone(boxes)
        self.assertEqual(generation, 7)
        self.camera.release.assert_called_once()

    def test_detector_failure_is_unknown_and_recreated(self):
        self.camera.read.return_value = (True, np.zeros((360, 640, 3), dtype=np.uint8))
        self.worker.detector.detect.side_effect = RuntimeError("test")
        detector = self.worker.detector
        self.worker.tick()
        self.assertIsNone(self.worker.take_sample()[0])
        self.assertIsNone(self.worker.detector)
        detector.close.assert_called_once()

    def test_success_without_faces_is_real_absence(self):
        self.camera.read.return_value = (True, np.zeros((360, 640, 3), dtype=np.uint8))
        self.worker.detector.detect.return_value = []
        self.worker.tick()
        self.assertEqual(self.worker.take_sample()[0], ())
        self.assertIsNone(self.worker.take_sample())

    def test_delayed_read_is_unknown_and_reopens_camera(self):
        self.camera.read.return_value = (True, np.zeros((360, 640, 3), dtype=np.uint8))
        with patch("detection.camera_worker.time.monotonic", side_effect=[0., 0., 1.1, 1.1, 1.1, 1.1]):
            self.worker.tick()
        self.assertIsNone(self.worker.take_sample()[0])
        self.assertIsNone(self.worker.camera)
        self.camera.release.assert_called_once()
        self.worker.detector.detect.assert_not_called()
        self.assertIn("capture stalled", self.worker.last_status)

    def test_slow_first_frame_can_warm_up_without_reopen_loop(self):
        self.worker.warming_up = True
        self.camera.read.return_value = (True, np.zeros((360, 640, 3), dtype=np.uint8))
        with patch("detection.camera_worker.time.monotonic", side_effect=[0., 0., 1.1, 1.1]):
            self.worker.tick()
        self.camera.release.assert_not_called()
        self.worker.detector.detect.assert_not_called()
        self.assertIsNone(self.worker.take_sample())
        self.worker.detector.detect.return_value = []
        self.worker.tick()
        self.assertEqual(self.worker.take_sample()[0], ())
        self.assertEqual(self.worker.last_status, "Camera ready")

    def test_snooze_releases_camera_and_drops_samples(self):
        self.worker.sample = ((), 0, 7)
        self.worker.set_monitoring(False, 8)
        self.camera.release.assert_called_once()
        self.assertIsNone(self.worker.take_sample())
        self.assertFalse(self.worker.timer.isActive())


if __name__ == "__main__":
    unittest.main()
