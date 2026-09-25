"""Synthetic wet-glass preview and native GPU timing; never captures the desktop."""
import argparse
import json
from pathlib import Path
import sys
import time
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
from PySide6.QtCore import QTimer, QRectF
from PySide6.QtGui import QColor, QImage, QPainter, QLinearGradient, QRadialGradient
from PySide6.QtWidgets import QApplication, QWidget
from ui.glass import frost
from ui.glass_compositor import GlassCompositor
from ui.rain import RainWindow


def synthetic_surface(width, height):
    scene = QImage(width, height, QImage.Format.Format_RGBA8888)
    painter = QPainter(scene)
    gradient = QLinearGradient(0, 0, width, height)
    gradient.setColorAt(0, QColor('#355369'))
    gradient.setColorAt(.4, QColor('#142536'))
    gradient.setColorAt(1, QColor('#827264'))
    painter.fillRect(scene.rect(), gradient)
    # Low-contrast office/window forms, then the unchanged privacy pipeline.
    for x, y, w, h, color in [(.06,.14,.26,.51,'#385c6b'), (.40,.22,.2,.47,'#897464'),
                                (.73,.02,.12,.8,'#6d8b93'), (.0,.85,1,.15,'#243242')]:
        painter.fillRect(QRectF(x*width,y*height,w*width,h*height), QColor(color))
    for x,y,r,color in [(.19,.29,.18,'#74868b'),(.6,.4,.17,'#b29771'),(.88,.18,.15,'#8a9fa6')]:
        light = QRadialGradient(x*width,y*height,r*height)
        light.setColorAt(0,QColor(color)); light.setColorAt(1,QColor(0,0,0,0))
        painter.fillRect(scene.rect(),light)
    painter.end()
    return GlassCompositor().compose(frost(scene), width, height)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--seconds', type=float, default=8)
    parser.add_argument('--warmup', type=float, default=0,
                        help='Simulation seconds to age the surface before rendering')
    parser.add_argument('--output', default='build/rain-preview.png')
    parser.add_argument('--seed', type=int, default=23,
                        help='Deterministic layout seed')
    parser.add_argument('--fullscreen', action='store_true')
    args = parser.parse_args()
    app = QApplication([])
    widget = RainWindow(seed=args.seed)
    class Host(QWidget):
        def resizeEvent(self, event):
            super().resizeEvent(event)
            container.setGeometry(self.rect().adjusted(0, 0, 1, 1))
    host = Host()
    host.setWindowTitle('DeskVeil — synthetic rain study')
    container = QWidget.createWindowContainer(widget, host)
    host.resize(1280, 800)
    if args.fullscreen:
        host.showFullScreen()
    else:
        host.show()
    surface = synthetic_surface(round(host.width()*host.devicePixelRatioF()),
                                round(host.height()*host.devicePixelRatioF()))
    widget.start(surface)
    widget.timer.stop()
    app.processEvents()  # Create the native GL surface before a lengthy warmup.
    deadline = time.monotonic() + 15
    while widget.simulation is None and not widget.broken and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(.005)
    assert widget.simulation is not None, 'Rain layout preparation did not complete'
    widget.timer.stop()
    # Inspect freshly generated trails after the wide, prepopulated water
    # paths have expired, rather than judging only the initial composition.
    for _ in range(round(max(0, args.warmup)*20)):
        widget.simulation.step(.05)
    widget.last_step = time.monotonic()
    widget.timer.start()
    times = []
    widget.frameSwapped.connect(lambda: times.append(time.perf_counter()))
    cpu = time.process_time()
    start = time.perf_counter()
    early_frame = []
    if args.seconds >= 3:
        QTimer.singleShot(1500, lambda: early_frame.append(widget.grabFramebuffer().copy()))

    def finish():
        elapsed = time.perf_counter()-start
        cpu_time = time.process_time()-cpu
        output = Path(args.output)
        output.parent.mkdir(exist_ok=True, parents=True)
        rendered = widget.grabFramebuffer()
        rendered.copy(0, 0, surface.width(), surface.height()).save(str(output))
        changed_pixels = None
        if early_frame:
            before = early_frame[0].convertToFormat(QImage.Format.Format_RGBA8888)
            after = rendered.convertToFormat(QImage.Format.Format_RGBA8888)
            a = np.frombuffer(before.constBits(), np.uint8).reshape(-1,4).astype(np.int16)
            b = np.frombuffer(after.constBits(), np.uint8).reshape(-1,4).astype(np.int16)
            changed_pixels = int(np.count_nonzero(np.max(np.abs(a[:,:3]-b[:,:3]),axis=1) > 8))
            assert changed_pixels > 1000, 'Rain stayed visually static over a fixed background'
        drop_count, trail_count = len(widget.simulation.drops), len(widget.simulation.trails)
        # With no water geometry, the GPU must reproduce the processed surface
        # exactly (orientation, channels, dimensions), including its dither.
        widget.timer.stop()
        widget.simulation.drops.clear()
        widget.simulation.trails.clear()
        widget.water_enabled = False
        widget.makeCurrent()
        widget.paintGL()
        plain = widget.grabFramebuffer().copy(0, 0, surface.width(), surface.height())
        plain = plain.convertToFormat(QImage.Format.Format_RGBA8888)
        widget.doneCurrent()
        expected = surface.convertToFormat(QImage.Format.Format_RGBA8888)
        actual_pixels = np.frombuffer(plain.constBits(), np.uint8).astype(np.int16)
        expected_pixels = np.frombuffer(expected.constBits(), np.uint8).astype(np.int16)
        error = int(np.abs(actual_pixels-expected_pixels).max())
        assert error <= 1, f'GPU altered the processed backdrop: {error}'
        # A dry Rain pane combines dark acrylic with the 98%-transparent white
        # film, independently of droplet highlights.
        widget.water_enabled = True
        widget.simulation.layout.condensation = np.empty((0, 10), np.float32)
        widget.simulation.static_revision += 1
        widget.makeCurrent()
        widget.paintGL()
        dark = widget.grabFramebuffer().copy(0, 0, surface.width(), surface.height())
        dark = dark.convertToFormat(QImage.Format.Format_RGBA8888)
        widget.doneCurrent()
        dark_pixels = np.frombuffer(dark.constBits(), np.uint8).reshape(-1, 4).astype(np.int16)
        dark_expected = np.rint(expected_pixels.reshape(-1, 4)[:, :3] * .85 * .98 + 255*.02)
        dark_error = int(np.abs(dark_pixels[:, :3] - dark_expected).max())
        assert dark_error <= 1, f'Rain material brightness changed: {dark_error}'
        steady = [t for t in times if t > start+1.5]
        gaps = np.diff(steady)*1000
        print(json.dumps({'valid':widget.isValid(), 'frames':widget.frames,
                          'fps':len(times)/elapsed, 'cpu_one_core_percent':cpu_time/elapsed*100,
                          'steady_fps':(len(steady)-1)/(steady[-1]-steady[0]) if len(steady)>1 else None,
                          'gap_median_ms':float(np.median(gaps)) if len(gaps) else None,
                          'gap_p95_ms':float(np.percentile(gaps,95)) if len(gaps) else None,
                          'uploads':widget.uploads, 'background_max_error':error,
                          'rain_brightness_max_error':dark_error,
                          'motion_changed_pixels':changed_pixels,
                          'physical_size':[plain.width(),plain.height()],
                          'drops':drop_count, 'trails':trail_count, 'image':str(output)}))
        host.hide()
        widget.stop()
        frames = widget.frames
        def verify_stopped():
            assert widget.frames == frames and not widget.timer.isActive()
            assert widget.texture is None
            widget.cleanup()
            app.quit()
        QTimer.singleShot(250, verify_stopped)
    QTimer.singleShot(round(args.seconds*1000), finish)
    app.exec()
    return 1 if widget.broken else 0


if __name__ == '__main__':
    sys.exit(main())
