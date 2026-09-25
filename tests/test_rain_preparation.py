import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import unittest
from concurrent.futures import Future
from unittest.mock import patch
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QImage
from ui.rain import RAIN_PATTERN_SEEDS, RainWindow

app = QApplication.instance() or QApplication([])


class RainPreparationTests(unittest.TestCase):
    def test_default_seed_comes_from_approved_patterns(self):
        with patch('ui.rain.random.SystemRandom') as system_random:
            system_random.return_value.choice.return_value = RAIN_PATTERN_SEEDS[3]
            rain = RainWindow()
        self.assertEqual(rain.seed, RAIN_PATTERN_SEEDS[3])
        rain.stop()

    def setUp(self):
        self.rain = RainWindow(seed=23)
        self.rain.resize(800, 600)
        self.future = Future()
        self.submit = patch('ui.rain._layout_worker.submit', return_value=self.future).start()
        self.render = patch.object(self.rain, 'start_rendering').start()

    def tearDown(self):
        self.rain.cancel_preparation()
        self.rain.stop()
        patch.stopall()

    def test_hidden_preparation_reuses_layout_without_starting_animation(self):
        self.rain.prepare_layout()
        self.rain.prepare_layout()
        self.submit.assert_called_once()
        self.assertFalse(self.rain.active)
        self.assertFalse(self.rain.timer.isActive())
        simulation = object()
        self.future.set_result(simulation)
        self.rain.finish_preparation()
        self.assertIs(self.rain.simulation, simulation)
        self.render.assert_not_called()
        self.rain.presented = True
        self.rain.start(QImage())
        self.assertFalse(self.rain.presented)
        self.render.assert_called_once()

    def test_reveal_during_preparation_does_not_start_a_late_cover(self):
        self.rain.start(QImage())
        self.render.assert_not_called()
        self.rain.stop()
        self.future.set_result(object())
        self.rain.finish_preparation()
        self.render.assert_not_called()
        self.assertFalse(self.rain.active)

    def test_cover_waits_for_layout_and_starts_when_it_completes(self):
        self.rain.start(QImage())
        self.render.assert_not_called()
        self.future.set_result(object())
        self.rain.finish_preparation()
        self.render.assert_called_once()
        self.assertFalse(self.rain.preparation_timer.isActive())

    def test_shutdown_cancels_queued_preparation(self):
        self.rain.prepare_layout()
        self.rain.cancel_preparation()
        self.assertTrue(self.future.cancelled())
        self.assertIsNone(self.rain.preparation)
        self.assertFalse(self.rain.preparation_timer.isActive())

    def test_resize_during_preparation_discards_wrong_size_result(self):
        self.rain.prepare_layout()
        self.rain.resize(1000, 700)
        self.future.set_result(object())
        replacement = Future()
        self.submit.return_value = replacement
        self.rain.finish_preparation()
        self.assertIsNone(self.rain.simulation)
        self.assertIs(self.rain.preparation, replacement)
        self.assertEqual(self.rain.preparation_size, (1000, 700))

    def test_preparation_failure_uses_existing_renderer_fallback(self):
        failures = []
        self.rain.failed.connect(lambda: failures.append(True))
        self.rain.prepare_layout()
        self.future.set_exception(RuntimeError('layout failure'))
        self.rain.finish_preparation()
        self.assertTrue(self.rain.broken)
        self.assertEqual(failures, [True])
        self.assertFalse(self.rain.preparation_timer.isActive())
