"""Frost a desktop frame in RAM; never store captures on disk."""
import cv2
import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage
import config


def frost(image):
    return blur_small(downsample(image))


def downsample(image):
    if image.isNull():
        return QImage()
    # Bound both computation and retained detail. Blur after downsampling so
    # desktop text never appears as a merely translucent sharp screenshot.
    # Compare the compact resized pixels before converting changed frames to
    # RGBA64. The conversion is lossless and only needed when blurring.
    return image.scaled(config.GLASS_MAX_EDGE, config.GLASS_MAX_EDGE,
                        Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
                        )


def blur_small(small):
    if small.isNull():
        return QImage()
    small = small.convertToFormat(QImage.Format.Format_RGBA64)
    pixels = np.frombuffer(small.constBits(), dtype=np.uint16).reshape(small.height(), small.bytesPerLine() // 2)
    pixels = pixels[:, :small.width() * 4].reshape(small.height(), small.width(), 4)
    result = QImage(small.width(), small.height(), QImage.Format.Format_RGBA64)
    blurred = np.frombuffer(result.bits(), dtype=np.uint16).reshape(small.height(), small.width(), 4)
    # Write into Qt-owned memory directly: no temporary output plus deep copy.
    cv2.GaussianBlur(pixels, (0, 0), config.GLASS_BLUR_SIGMA, dst=blurred, borderType=cv2.BORDER_REFLECT_101)
    blurred[:, :, 3] = 65535
    return result

