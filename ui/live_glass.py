"""Reusable desktop capture on a worker; a single latest-frame mailbox."""
import ctypes
from ctypes import wintypes
import logging
import threading
import time
from PySide6.QtGui import QImage
from ui.glass import downsample, blur_small
from ui.glass_compositor import GlassCompositor, GlassFrame
import config


class BitmapInfo(ctypes.Structure):
    _fields_ = [('size', wintypes.DWORD), ('width', wintypes.LONG),
                ('height', wintypes.LONG), ('planes', wintypes.WORD),
                ('bits', wintypes.WORD), ('compression', wintypes.DWORD),
                ('image_size', wintypes.DWORD), ('xppm', wintypes.LONG),
                ('yppm', wintypes.LONG), ('used', wintypes.DWORD), ('important', wintypes.DWORD)]


class DesktopCapture:
    def __init__(self, bounds):
        self.x, self.y, self.width, self.height = bounds
        self.api = ctypes.windll.gdi32
        user = ctypes.windll.user32
        user.GetDC.argtypes = [wintypes.HWND]
        user.GetDC.restype = wintypes.HDC
        self.api.CreateCompatibleDC.argtypes = [wintypes.HDC]
        self.api.CreateCompatibleDC.restype = wintypes.HDC
        self.api.CreateDIBSection.argtypes = [wintypes.HDC, ctypes.POINTER(BitmapInfo), wintypes.UINT,
                                             ctypes.POINTER(ctypes.c_void_p), wintypes.HANDLE, wintypes.DWORD]
        self.api.CreateDIBSection.restype = wintypes.HBITMAP
        self.api.SelectObject.argtypes = [wintypes.HDC, wintypes.HANDLE]
        self.api.SelectObject.restype = wintypes.HANDLE
        self.api.BitBlt.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                    wintypes.HDC, ctypes.c_int, ctypes.c_int, wintypes.DWORD]
        self.api.DeleteObject.argtypes = [wintypes.HANDLE]
        self.api.DeleteDC.argtypes = [wintypes.HDC]
        self.screen = user.GetDC(None)
        self.memory = self.api.CreateCompatibleDC(self.screen)
        self.pixels = ctypes.c_void_p()
        info = BitmapInfo()
        info.size = ctypes.sizeof(info)
        info.width, info.height, info.planes, info.bits = self.width, -self.height, 1, 32
        self.bitmap = self.api.CreateDIBSection(self.screen, ctypes.byref(info), 0, ctypes.byref(self.pixels), None, 0)
        self.old = self.api.SelectObject(self.memory, self.bitmap) if self.bitmap else None
        if not self.screen or not self.memory or not self.bitmap:
            self.close()
            raise OSError('Could not allocate desktop capture bitmap')
        self.buffer = (ctypes.c_ubyte * (self.width * self.height * 4)).from_address(self.pixels.value)

    def read(self):
        if not self.api.BitBlt(self.memory, 0, 0, self.width, self.height, self.screen,
                               self.x, self.y, 0x00CC0020 | 0x40000000):
            return QImage()
        self.api.GdiFlush()
        # The bitmap lives until the next read; frost makes its own result.
        return QImage(self.buffer, self.width, self.height, self.width * 4, QImage.Format.Format_RGB32)

    def close(self):
        if self.old:
            self.api.SelectObject(self.memory, self.old)
            self.old = None
        if self.bitmap:
            self.api.DeleteObject(self.bitmap)
            self.bitmap = None
        if self.memory:
            self.api.DeleteDC(self.memory)
            self.memory = None
        if self.screen:
            ctypes.windll.user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
            ctypes.windll.user32.ReleaseDC(None, self.screen)
            self.screen = None


class LiveGlass:
    def __init__(self, notify=None):
        self.condition = threading.Condition()
        self.request = None
        self.epoch = 0
        self.frame = None
        self.closed = False
        self.notify = notify
        self.thread = threading.Thread(target=self.run, name='DeskVeil glass', daemon=True)
        self.thread.start()

    def start(self, bounds):
        with self.condition:
            if self.request != bounds:
                self.epoch += 1
                self.frame = None
                self.request = bounds
            self.condition.notify()

    def stop(self):
        with self.condition:
            self.epoch += 1
            self.request = None
            self.frame = None
            self.condition.notify()

    def take(self):
        with self.condition:
            frame, self.frame = self.frame, None
            return frame

    def close(self):
        with self.condition:
            self.closed = True
            self.frame = None
            self.condition.notify()
        self.thread.join()

    def run(self):
        capture = None
        bounds = None
        previous = QImage()
        previous_epoch = None
        compositor = GlassCompositor()
        try:
            while True:
                with self.condition:
                    while self.request is None and not self.closed:
                        if capture:
                            capture.close()
                            capture = None
                        previous = QImage()
                        small = QImage()
                        frame = None
                        previous_epoch = None
                        compositor.clear()
                        self.condition.wait()
                    if self.closed:
                        return
                    requested, epoch = self.request, self.epoch
                started = time.monotonic()
                try:
                    if capture is None or bounds != requested:
                        if capture:
                            capture.close()
                        capture = None
                        capture = DesktopCapture(requested)
                        bounds = requested
                    small = downsample(capture.read())
                    # Comparing actual pixels avoids repeated blur/repaint of an
                    # unchanged desktop, without reducing the capture cadence.
                    if epoch == previous_epoch and small == previous and not small.isNull():
                        frame = None
                    else:
                        background = blur_small(small)
                        frame = GlassFrame(background, compositor.compose(background, requested[2], requested[3]))
                        background = QImage()
                    previous, previous_epoch = small, epoch
                except Exception:
                    logging.getLogger('deskveil').exception('Live glass capture failed')
                    frame = GlassFrame(QImage(), QImage())
                notify = False
                with self.condition:
                    if epoch == self.epoch and not self.closed:
                        if frame is not None:
                            notify = self.frame is None
                            self.frame = frame
                # A queued UI signal is only needed when the mailbox becomes
                # nonempty. Newer frames replace pending ones without queuing.
                if notify and self.notify:
                    self.notify()
                with self.condition:
                    if epoch == self.epoch and not self.closed:
                        self.condition.wait(timeout=max(.001, 1 / config.GLASS_FPS - (time.monotonic() - started)))
        finally:
            compositor.clear()
            if capture:
                capture.close()
