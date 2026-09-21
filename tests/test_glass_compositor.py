import unittest
import numpy as np
from PySide6.QtGui import QImage
from ui.glass_compositor import GlassCompositor


class CompositorTests(unittest.TestCase):
    def test_fractional_dark_tone_survives_final_output_without_flicker(self):
        compositor = GlassCompositor()
        compositor.prepare(512, 256)
        work = np.frombuffer(compositor.work.bits(), np.uint16).reshape(256, 512, 4)
        work[:, :, :3] = round(30.5 * 257)
        work[:, :, 3] = 65535
        output = compositor.quantize()
        pixels = np.frombuffer(output.constBits(), np.uint8).reshape(256, 512, 4)
        self.assertEqual(set(np.unique(pixels[:, :, 0])), {30, 31})
        self.assertAlmostEqual(float(pixels[:, :, 0].mean()), 30.5, delta=.01)
        self.assertTrue(np.all(pixels[:, :, 3] == 255))
        self.assertEqual(output, compositor.quantize())

    def test_flat_material_has_no_large_scale_brightness_rings(self):
        source = QImage(512, 512, QImage.Format.Format_RGBA64)
        source.fill(0xff303030)
        compositor = GlassCompositor()
        output = compositor.compose(source, 512, 512)
        pixels = np.frombuffer(output.constBits(), np.uint8).reshape(512, 512, 4)
        self.assertTrue(np.array_equal(pixels[:256, :256], pixels[256:, 256:]))
        compositor.clear()
        self.assertFalse(np.any(np.frombuffer(compositor.work.constBits(), np.uint16)))

    def test_quantization_clamps_dither_at_black_and_white(self):
        compositor = GlassCompositor()
        compositor.prepare(256, 128)
        for color, expected in [(0xff000000, 0), (0xffffffff, 255)]:
            compositor.work.fill(color)
            output = compositor.quantize()
            pixels = np.frombuffer(output.constBits(), np.uint8).reshape(128, 256, 4)
            self.assertLessEqual(np.abs(pixels[:, :, :3].astype(np.int16) - expected).max(), 1)
            self.assertAlmostEqual(float(pixels[:, :, :3].mean()), expected, delta=.15)
            self.assertTrue(np.all(pixels[:, :, 3] == 255))
