"""Generate old/new material comparison from synthetic gradients only."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
from PySide6.QtCore import QRect
from PySide6.QtGui import QImage, QPainter, QColor, QLinearGradient, QRadialGradient, QBrush
from ui.glass import frost
from ui.glass_compositor import GlassCompositor
import config


def grain_tile():
    # Previous material's translucent grain, retained only for comparison.
    rng = np.random.default_rng(71)
    values = np.where(rng.random((128, 128)) < .5, 0, 255).astype(np.uint8)
    pixels = np.empty((128, 128, 4), dtype=np.uint8)
    pixels[:, :, :3] = values[:, :, None]
    pixels[:, :, 3] = 2
    return QImage(pixels.data, 128, 128, pixels.strides[0], QImage.Format.Format_RGBA8888).copy()


def main():
    width, height = 1280, 800
    y, x = np.mgrid[:height, :width]
    radius = np.sqrt(((x-width*.45)/width)**2+((y-height*.45)/height)**2)
    pixels = np.zeros((height, width, 4), np.uint8)
    for channel, offset in enumerate((22, 30, 44)):
        pixels[:, :, channel] = offset + radius * 35
    pixels[:, :, 3] = 255
    source = QImage(pixels.data, width, height, pixels.strides[0], QImage.Format.Format_RGBA8888)
    blurred = frost(source)
    old = QImage(width, height, QImage.Format.Format_RGB32)
    tint = QImage(width, height, QImage.Format.Format_RGBA64_Premultiplied)
    tint.fill(QColor(8, 14, 23, config.GLASS_DIM_ALPHA))
    painter = QPainter(tint)
    wash = QLinearGradient(0, 0, width, height)
    for position, color in [(0., QColor(180, 205, 235, 12)), (.5, QColor(90, 115, 150, 4)), (1., QColor(30, 45, 70, 20))]:
        wash.setColorAt(position, color)
    painter.fillRect(tint.rect(), wash)
    glow = QRadialGradient(width*.16, height*.12, width*.8)
    glow.setColorAt(0., QColor(220, 235, 255, 8))
    glow.setColorAt(1., QColor(255, 255, 255, 0))
    painter.fillRect(tint.rect(), glow)
    painter.fillRect(tint.rect(), QBrush(grain_tile()))
    painter.end()
    painter = QPainter(old)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    painter.drawImage(old.rect(), blurred)
    painter.drawImage(0, 0, tint)
    painter.end()
    new = GlassCompositor().compose(blurred, width, height)
    output = QImage(width*2, height, QImage.Format.Format_RGB32)
    painter = QPainter(output)
    painter.drawImage(0, 0, old)
    painter.drawImage(width, 0, new)
    painter.end()
    path = Path(__file__).resolve().parents[1] / 'glass-quality.png'
    output.save(str(path))
    print(f'Old left / new right: {path}')


if __name__ == '__main__':
    main()
