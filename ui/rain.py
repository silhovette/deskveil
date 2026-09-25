"""Optional GPU skin. Receives only the final privacy surface, never a capture."""
import logging
import ctypes
from ctypes import wintypes
import random
import sys
import time
from concurrent.futures import ThreadPoolExecutor
import numpy as np
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QImage, QSurfaceFormat, QVector2D, QCursor
from PySide6.QtOpenGL import (QOpenGLBuffer, QOpenGLShader, QOpenGLShaderProgram, QOpenGLTexture,
                             QOpenGLWindow, QOpenGLFramebufferObject, QOpenGLFramebufferObjectFormat)
from ui.rain_shaders import VERTEX, FRAGMENT, HEIGHT_FRAGMENT

PATTERN_SCALE = 3.0
ANIMATION_SPEED = 1.4
# Approved static layouts. A new RainWindow chooses one seed from this list;
# each seed reproduces the same initial condensation and stationary drops.
RAIN_PATTERN_SEEDS = (
    102, 105, 107, 112, 117, 119, 124, 125, 130, 132, 134,
    136, 140, 144, 145, 149, 150, 153, 157, 159, 160,
)
_layout_worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix='DeskVeil rain preparation')


def prepare_simulation(width, height, seed):
    # Import SciPy on the worker too, so the first Rain toggle stays responsive.
    from ui.rain_simulation import RainSimulation
    return RainSimulation(width, height, seed, pattern_scale=PATTERN_SCALE)


def visible_shapes(shapes, width, height, pattern_scale):
    """Cull only quads wholly outside the viewport, including rotated trails."""
    # Match the shader's rotated +/-1.2 corners before the center zoom.
    # An extra logical pixel conservatively covers float32 boundary rounding.
    half_width = width / (2 * pattern_scale) + 1
    half_height = height / (2 * pattern_scale) + 1
    extent_x = 1.2 * (np.abs(shapes[:, 4]) * shapes[:, 2] +
                      np.abs(shapes[:, 5]) * shapes[:, 3])
    extent_y = 1.2 * (np.abs(shapes[:, 5]) * shapes[:, 2] +
                      np.abs(shapes[:, 4]) * shapes[:, 3])
    return shapes[(np.abs(shapes[:, 0] - width / 2) <= half_width + extent_x) &
                  (np.abs(shapes[:, 1] - height / 2) <= half_height + extent_y)]


def visible_shapes_into(shapes, width, height, pattern_scale, mask, output):
    """Cull into reusable buffers while preserving visible_shapes row order."""
    count = len(shapes)
    if not count:
        return output[:0]
    half_width = width / (2 * pattern_scale) + 1
    half_height = height / (2 * pattern_scale) + 1
    extent_x = 1.2 * (np.abs(shapes[:, 4]) * shapes[:, 2] + np.abs(shapes[:, 5]) * shapes[:, 3])
    extent_y = 1.2 * (np.abs(shapes[:, 5]) * shapes[:, 2] + np.abs(shapes[:, 4]) * shapes[:, 3])
    np.less_equal(np.abs(shapes[:, 0] - width / 2), half_width + extent_x, out=mask[:count])
    np.logical_and(mask[:count], np.less_equal(np.abs(shapes[:, 1] - height / 2), half_height + extent_y), out=mask[:count])
    kept = int(np.count_nonzero(mask[:count]))
    if kept:
        output[:kept] = shapes[mask[:count]]
    return output[:kept]


class RainWindow(QOpenGLWindow):
    failed = Signal()
    ready = Signal()

    def __init__(self, parent=None, seed=None):
        super().__init__(parent=parent)
        fmt = QSurfaceFormat()
        fmt.setVersion(2, 1)
        fmt.setDepthBufferSize(0)
        fmt.setStencilBufferSize(0)
        fmt.setSamples(0)
        fmt.setSwapInterval(1)
        self.setFormat(fmt)
        self.setFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setCursor(QCursor(Qt.CursorShape.BlankCursor))
        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.setInterval(16)
        self.timer.timeout.connect(self.advance)
        self.simulation = None
        self.preparation = None
        self.preparation_size = None
        self.preparation_timer = QTimer(self)
        self.preparation_timer.setInterval(16)
        self.preparation_timer.timeout.connect(self.finish_preparation)
        self.seed = (random.SystemRandom().choice(RAIN_PATTERN_SEEDS)
                     if seed is None else seed)
        self.active = False
        self.presented = False
        self.frameSwapped.connect(self.mark_presented)
        self.broken = False
        self.program = self.buffer = self.texture = None
        self.height_program = self.static_field = self.flow_field = None
        self._attribute_locations = {}
        self._uniform_locations = {}
        self.field_revision = None
        self.water_enabled = True
        self.pending_surface = QImage()
        self.uploaded_key = None
        self.last_step = 0.
        self.frames = 0
        self.uploads = 0
        self.corners = np.array([[-1.2,-1.2], [1.2,-1.2], [-1.2,1.2],
                                 [-1.2,1.2], [1.2,-1.2], [1.2,1.2]], np.float32)
        self.vertices = np.zeros((1, 6, 12), np.float32)
        self.visible_mask = np.empty(1, dtype=bool)
        self.visible_buffer = np.empty((1, 10), dtype=np.float32)
        self.backdrop_vertices = np.zeros((6, 12), np.float32)
        self.backdrop_vertices[:, :2] = self.corners / 1.2

    def set_surface(self, surface):
        # QImage is implicitly shared. Upload only a new processed frame, not
        # on each 60 Hz animation tick. No copies/readbacks at animation rate.
        self.pending_surface = surface

    def start(self, surface):
        if self.broken:
            self.failed.emit()
            return
        self.set_surface(surface)
        self.active = True
        # Every cover waits for its own first frame, including texture upload.
        self.presented = False
        self.prepare_layout()
        if self.simulation is not None:
            self.start_rendering()

    def prepare_layout(self):
        if self.broken or self.simulation is not None:
            return
        if self.preparation is None:
            self.preparation_size = (self.width(), self.height())
            self.preparation = _layout_worker.submit(
                prepare_simulation, *self.preparation_size, self.seed)
        self.preparation_timer.start()

    def finish_preparation(self):
        if self.preparation is None or not self.preparation.done():
            return
        future, self.preparation = self.preparation, None
        self.preparation_timer.stop()
        try:
            simulation = future.result()
        except Exception as error:
            self.fail(str(error))
            return
        if self.preparation_size != (self.width(), self.height()):
            # A hidden container can resize while the worker is running.
            self.prepare_layout()
            return
        self.simulation = simulation
        if self.active:
            self.start_rendering()

    def start_rendering(self):
        self.last_step = time.monotonic()
        if sys.platform == 'win32':
            api = ctypes.windll.user32
            api.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
            api.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]
            hwnd = int(self.winId())
            api.SetWindowLongW(hwnd, -20, api.GetWindowLongW(hwnd, -20) | 0x08000000)
        self.show()
        self.update()
        self.timer.start()

    def mark_presented(self):
        if self.active and self.simulation is not None and self.texture and not self.presented:
            self.presented = True
            self.ready.emit()

    def stop(self):
        self.active = False
        self.timer.stop()
        self.hide()
        self.pending_surface = QImage()
        self.uploaded_key = None
        if self.context() and self.texture:
            self.makeCurrent()
            self.texture.destroy()
            self.texture = None
            self.doneCurrent()

    def advance(self):
        if not self.active or not self.isVisible():
            self.timer.stop()
            return
        if self.simulation is None:
            return
        if not self.isValid():
            self.fail('OpenGL context creation failed')
            return
        now = time.monotonic()
        self.simulation.step((now - self.last_step) * ANIMATION_SPEED)
        self.last_step = now
        self.update()

    def exposeEvent(self, event):
        super().exposeEvent(event)
        if not self.isExposed():
            self.timer.stop()
        elif self.active and self.simulation is not None:
            self.last_step = time.monotonic()
            self.timer.start()

    def resizeGL(self, width, height):
        if self.simulation:
            self.simulation.resize(width, height)

    def initializeGL(self):
        self.presented = False
        self.context().aboutToBeDestroyed.connect(self.cleanup)
        self.program = QOpenGLShaderProgram()
        if not (self.program.addShaderFromSourceCode(QOpenGLShader.ShaderTypeBit.Vertex, VERTEX)
                and self.program.addShaderFromSourceCode(QOpenGLShader.ShaderTypeBit.Fragment, FRAGMENT)
                and self.program.link()):
            self.fail(self.program.log())
            return
        self.buffer = QOpenGLBuffer(QOpenGLBuffer.Type.VertexBuffer)
        self.buffer.create()
        self.buffer.setUsagePattern(QOpenGLBuffer.UsagePattern.StreamDraw)
        self.height_program = QOpenGLShaderProgram()
        if not (self.height_program.addShaderFromSourceCode(QOpenGLShader.ShaderTypeBit.Vertex, VERTEX)
                and self.height_program.addShaderFromSourceCode(QOpenGLShader.ShaderTypeBit.Fragment, HEIGHT_FRAGMENT)
                and self.height_program.link()):
            self.fail(self.height_program.log())
        self._uniform_locations = {
            'height_patternScale': self.height_program.uniformLocation('patternScale'),
            'height_backdrop': self.height_program.uniformLocation('backdrop'),
            'water_backdrop': self.program.uniformLocation('backdrop'),
            'water_frosted': self.program.uniformLocation('frosted'),
            'water_condensation': self.program.uniformLocation('condensation'),
            'water_flowing': self.program.uniformLocation('flowing'),
            'water_enabled': self.program.uniformLocation('waterEnabled'),
        }

    def fail(self, reason):
        logging.getLogger('deskveil').error('Rain renderer unavailable: %s', reason)
        self.broken = True
        self.timer.stop()
        self.cancel_preparation()
        self.failed.emit()

    def cancel_preparation(self):
        self.preparation_timer.stop()
        if self.preparation is not None:
            self.preparation.cancel()
            self.preparation = None

    def cleanup(self):
        self.cancel_preparation()
        if self.texture is None and self.buffer is None and self.program is None:
            return
        self.timer.stop()
        # Explicit shutdown runs while the QWindow is fully alive. Do not call
        # back into it again from its context's later native destructor.
        self.context().aboutToBeDestroyed.disconnect(self.cleanup)
        self.makeCurrent()
        if self.texture:
            self.texture.destroy()
        if self.buffer:
            self.buffer.destroy()
        if self.program:
            self.program.removeAllShaders()
        if self.height_program:
            self.height_program.removeAllShaders()
        self.height_program = self.static_field = self.flow_field = None
        self.field_revision = None
        self.texture = self.buffer = self.program = None
        self.uploaded_key = None
        self.doneCurrent()

    def upload_surface(self):
        image = self.pending_surface
        if image.isNull() or image.cacheKey() == self.uploaded_key:
            return
        if self.texture and (self.texture.width() != image.width() or self.texture.height() != image.height()):
            self.texture.destroy()
            self.texture = None
        if self.texture is None:
            self.texture = QOpenGLTexture(QOpenGLTexture.Target.Target2D)
            self.texture.setFormat(QOpenGLTexture.TextureFormat.RGBA8_UNorm)
            self.texture.setSize(image.width(), image.height())
            self.texture.setMipLevels(1)
            self.texture.allocateStorage()
            self.texture.setMinMagFilters(QOpenGLTexture.Filter.Linear, QOpenGLTexture.Filter.Linear)
            self.texture.setWrapMode(QOpenGLTexture.WrapMode.ClampToEdge)
        # GlassCompositor returns RGBA8888. Conversion is only for synthetic
        # preview/test images; keep the owned QImage alive during the upload.
        if image.format() != QImage.Format.Format_RGBA8888:
            image = image.convertToFormat(QImage.Format.Format_RGBA8888)
        self.texture.setData(QOpenGLTexture.PixelFormat.RGBA,
                             QOpenGLTexture.PixelType.UInt8, image.constBits())
        self.uploaded_key = self.pending_surface.cacheKey()
        self.uploads += 1

    def draw(self, vertices, program=None):
        program = program or self.program
        data = vertices.tobytes()
        self.buffer.bind()
        self.buffer.allocate(data, len(data))
        key = id(program)
        locations = self._attribute_locations.get(key)
        if locations is None:
            locations = tuple(program.attributeLocation(name)
                              for name in ('cornerCenter', 'radiiRotation', 'style'))
            self._attribute_locations[key] = locations
        for location, offset in zip(locations, (0, 16, 32)):
            if location >= 0:
                program.enableAttributeArray(location)
                program.setAttributeBuffer(location, 0x1406, offset, 4, 48)
        self.context().functions().glDrawArrays(0x0004, 0, vertices.size//12)
        self.buffer.release()

    def draw_shapes(self, shapes):
        count = len(shapes)
        if len(self.visible_mask) < count:
            self.visible_mask = np.empty(count + 128, dtype=bool)
        if len(self.visible_buffer) < count:
            self.visible_buffer = np.empty((count + 128, 10), dtype=np.float32)
        shapes = visible_shapes_into(shapes, self.width(), self.height(), PATTERN_SCALE,
                                    self.visible_mask, self.visible_buffer)
        count = len(shapes)
        if not count:
            return
        if len(self.vertices) < count:
            self.vertices = np.empty((count+128, 6, 12), np.float32)
        vertices = self.vertices[:count]
        vertices[:, :, :2] = self.corners
        vertices[:, :, 2:] = shapes[:, None, :]
        self.draw(vertices, self.height_program)

    def render_water(self):
        functions = self.context().functions()
        width, height = round(self.width()*self.devicePixelRatio()), round(self.height()*self.devicePixelRatio())
        revision = (width, height, self.simulation.static_revision)
        rebuild = revision != self.field_revision
        if rebuild:
            for attr, format_value in [('static_field',0x822D), ('flow_field',0x881A)]:
                fmt = QOpenGLFramebufferObjectFormat()
                fmt.setInternalTextureFormat(format_value)  # R16F / RGBA16F (drop mask)
                field = QOpenGLFramebufferObject(width,height,fmt)
                if not field.isValid():
                    raise RuntimeError('Water height framebuffer unavailable')
                setattr(self,attr,field)
                functions.glBindTexture(0x0DE1,field.texture())
                functions.glTexParameteri(0x0DE1,0x2801,0x2601)
                functions.glTexParameteri(0x0DE1,0x2800,0x2601)
                functions.glTexParameteri(0x0DE1,0x2802,0x812F)
                functions.glTexParameteri(0x0DE1,0x2803,0x812F)
            self.field_revision = revision
        self.height_program.bind()
        self.height_program.setUniformValue('viewport',QVector2D(self.width(),self.height()))
        # Zoom the entire wet surface about its center: sizes, spacing, trails
        # and motion together. The processed desktop texture stays unscaled.
        self.height_program.setUniformValue1f(self._uniform_locations['height_patternScale'], PATTERN_SCALE)
        self.height_program.setUniformValue1i(self._uniform_locations['height_backdrop'], 0)
        functions.glViewport(0,0,width,height)
        functions.glClearColor(0.,0.,0.,0.)
        functions.glEnable(0x0BE2)
        functions.glBlendFunc(1,1)  # Water volumes combine before lighting.
        if rebuild:
            self.static_field.bind()
            functions.glClear(0x4000)
            self.draw_shapes(self.simulation.layout.condensation)
        self.flow_field.bind()
        functions.glClear(0x4000)
        # Connected trail segments share one film height; adding their overlap
        # produces ridges and bright seams along an otherwise smooth path.
        functions.glBlendEquation(0x8008)  # GL_MAX
        self.draw_shapes(self.simulation.shape_array())
        functions.glBlendEquation(0x8006)  # GL_FUNC_ADD
        functions.glDisable(0x0BE2)
        self.height_program.release()
        functions.glBindFramebuffer(0x8D40,self.defaultFramebufferObject())

    def paintGL(self):
        try:
            self.render_gl()
        except Exception as error:
            self.fail(str(error))

    def render_gl(self):
        functions = self.context().functions()
        functions.glClearColor(.153, .2, .275, 1.)
        functions.glClear(0x4000)
        if self.broken or not self.program or not self.active or self.simulation is None:
            return
        self.upload_surface()
        if not self.texture:
            return
        self.render_water()
        self.program.bind()
        self.program.setUniformValue('viewport', QVector2D(self.width(), self.height()))
        self.program.setUniformValue('surfaceScale', QVector2D(
            self.width()*self.devicePixelRatio()/self.texture.width(),
            self.height()*self.devicePixelRatio()/self.texture.height()))
        self.program.setUniformValue1i(self._uniform_locations['water_frosted'], 0)
        self.program.setUniformValue1i(self._uniform_locations['water_condensation'], 1)
        self.program.setUniformValue1i(self._uniform_locations['water_flowing'], 2)
        self.program.setUniformValue1i(self._uniform_locations['water_enabled'], int(self.water_enabled))
        self.program.setUniformValue('fieldTexel',QVector2D(1/self.static_field.width(),1/self.static_field.height()))
        self.program.setUniformValue1f(self.program.uniformLocation('pixelRatio'),float(self.devicePixelRatio()))
        for unit,field in [(1,self.static_field),(2,self.flow_field)]:
            functions.glActiveTexture(0x84C0+unit)
            functions.glBindTexture(0x0DE1,field.texture())
        self.texture.bind(0)
        functions.glDisable(0x0BE2)
        self.program.setUniformValue1i(self._uniform_locations['water_backdrop'], 1)
        self.draw(self.backdrop_vertices)
        self.texture.release()
        self.program.release()
        self.frames += 1
