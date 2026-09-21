import unittest
import numpy as np
from PySide6.QtGui import QImage
from ui.glass import frost


class GlassTests(unittest.TestCase):
    def test_fine_detail_is_blurred_and_result_is_opaque(self):
        pixels = np.zeros((240, 320, 4), dtype=np.uint8)
        pixels[:, ::2, :3] = 255
        pixels[:, :, 3] = 255
        image = QImage(pixels.data, 320, 240, pixels.strides[0], QImage.Format.Format_RGBA8888)
        result = frost(image)
        display = result.convertToFormat(QImage.Format.Format_RGBA8888)
        output = np.frombuffer(display.constBits(), dtype=np.uint8).reshape(display.height(), display.width(), 4)
        self.assertLess(output[20:-20, 20:-20, :3].std(), 5)
        self.assertTrue(np.all(output[:, :, 3] == 255))

    def test_missing_capture_stays_empty_for_solid_fallback(self):
        self.assertTrue(frost(QImage()).isNull())

    def test_gradient_retains_sub_byte_tones(self):
        pixels = np.zeros((128, 960, 4), dtype=np.uint8)
        pixels[:, :, :3] = np.linspace(20, 80, 960, dtype=np.uint8)[None, :, None]
        pixels[:, :, 3] = 255
        source = QImage(pixels.data, 960, 128, pixels.strides[0], QImage.Format.Format_RGBA8888)
        result = frost(source)
        values = np.frombuffer(result.constBits(), dtype=np.uint16).reshape(128, 960, 4)
        self.assertGreater(np.unique(values[64, 30:-30, 0]).size, 500)
        self.assertEqual(result, frost(source))

    def test_completed_frame_owns_its_pixels(self):
        source = QImage(96, 64, QImage.Format.Format_RGB32)
        source.fill(0xff123456)
        first = frost(source)
        saved = first.copy()
        source.fill(0xffabcdef)
        second = frost(source)
        self.assertEqual(first, saved)
        self.assertNotEqual(first, second)
