"""Differential pixel check and compute timings using generated frames only."""
from pathlib import Path
import sys
import statistics
import time
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import cv2
import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage
from ui.glass import downsample, blur_small
import config


def reference_downsample(image):
    return image.scaled(config.GLASS_MAX_EDGE, config.GLASS_MAX_EDGE,
                        Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
                        ).convertToFormat(QImage.Format.Format_RGBA64)


def reference_blur(small):
    small = small.convertToFormat(QImage.Format.Format_RGBA64)
    pixels = np.frombuffer(small.constBits(), np.uint16).reshape(small.height(), small.bytesPerLine() // 2)
    pixels = pixels[:, :small.width() * 4].reshape(small.height(), small.width(), 4)
    blurred = cv2.GaussianBlur(pixels, (0, 0), config.GLASS_BLUR_SIGMA, borderType=cv2.BORDER_REFLECT_101)
    blurred[:, :, 3] = 65535
    return QImage(blurred.data, small.width(), small.height(), blurred.strides[0], QImage.Format.Format_RGBA64).copy()


def main():
    rng = np.random.default_rng(9)
    pixels = rng.integers(0, 256, (1600, 2560, 4), dtype=np.uint8)
    pixels[:, :, 3] = 255
    source = QImage(pixels.data, 2560, 1600, pixels.strides[0], QImage.Format.Format_RGB32)
    expected = reference_blur(reference_downsample(source))
    actual = blur_small(downsample(source))
    assert actual == expected, 'Optimized blur changed pixel output'
    for name, resize, blur in [('reference', reference_downsample, reference_blur),
                               ('current', downsample, blur_small)]:
        for changing in (False, True):
            values = []
            previous = resize(source)
            for _ in range(5):
                blur(previous)
            for _ in range(40):
                start = time.perf_counter()
                small = resize(source)
                if changing or small != previous:
                    blur(small)
                previous = small
                values.append((time.perf_counter() - start) * 1000)
            print(f'{name} {"changing" if changing else "static"}: median={statistics.median(values):.2f}ms, '
                  f'p95={sorted(values)[37]:.2f}ms, comparison buffer={previous.sizeInBytes()/1024/1024:.2f}MiB')
    print('PASS: generated-frame pixel output is identical')


if __name__ == '__main__':
    main()
