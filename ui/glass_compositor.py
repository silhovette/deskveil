"""Compose in 16-bit, then dither once at the final physical-pixel output."""
from dataclasses import dataclass
import cv2
import numpy as np
from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QImage, QPainter
import config


@dataclass
class GlassFrame:
    background: QImage
    surface: QImage


class GlassCompositor:
    def __init__(self):
        self.work = QImage()
        self.noise = None
        self.scratch = None

    def prepare(self, width, height):
        if self.work.width() == width and self.work.height() == height and self.noise is not None:
            return
        self.work = QImage(width, height, QImage.Format.Format_RGBA64)
        # Rank high-pass noise so thresholds have an even distribution without
        # low-frequency clouds. Fixed in physical pixels: no moving grain.
        rng = np.random.default_rng(71)
        white = rng.random((256, 256), dtype=np.float32)
        padded = np.pad(white, 4, mode='wrap')
        high = white - cv2.GaussianBlur(padded, (9, 9), 1.0)[4:-4, 4:-4]
        ranks = np.empty(65536, dtype=np.uint32)
        ranks[np.argsort(high, axis=None)] = np.arange(65536, dtype=np.uint32)
        tile = (ranks.reshape(256, 256) * 257 // 65536).astype(np.uint16)
        # Triangular dither keeps a fine texture even at integer tone values;
        # single uniform thresholds can leave alternating smooth/grainy bands.
        tile = tile + np.roll(tile, (73, 119), axis=(0, 1))
        row = np.tile(tile, (1, (width + 255)//256))[:, :width]
        # Center once, rather than subtracting the bias over the whole display
        # every frame. Signed thresholds allow a saturating uint16 addition.
        self.noise = np.zeros((256, width, 4), dtype=np.int16)
        self.noise[:, :, :3] = row[:, :, None].astype(np.int16) - 256
        self.scratch = np.empty((64, width, 4), dtype=np.uint16)

    def clear(self):
        if not self.work.isNull():
            self.work.fill(0)
        if self.scratch is not None:
            self.scratch.fill(0)

    def compose(self, background, width, height):
        if background.isNull():
            return QImage()
        self.prepare(width, height)
        painter = QPainter(self.work)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        painter.drawImage(QRect(0, 0, width, height), background)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        # Uniform frosted material; no artificial radial rings or gradient LUTs.
        painter.fillRect(QRect(0, 0, width, height), QColor(16, 24, 36, config.GLASS_DIM_ALPHA))
        painter.end()
        return self.quantize()

    def quantize(self):
        height, width = self.work.height(), self.work.width()
        source = np.frombuffer(self.work.constBits(), np.uint16).reshape(height, width, 4)
        result = QImage(width, height, QImage.Format.Format_RGBA8888)
        output = np.frombuffer(result.bits(), np.uint8).reshape(height, width, 4)
        # Small row blocks avoid a full-resolution float/int temporary per frame.
        for first in range(0, height, 64):
            last = min(first + 64, height)
            scratch = self.scratch[:last-first]
            noise = self.noise[first % 256:first % 256 + last-first]
            # Saturation clamps both black and white during the addition,
            # eliminating float conversion and a separate full-image clamp.
            cv2.add(source[first:last], noise, dst=scratch, dtype=cv2.CV_16U)
            cv2.convertScaleAbs(scratch, dst=output[first:last], alpha=1/257)
        return result
