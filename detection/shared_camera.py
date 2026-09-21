"""Windows same-session camera sharing, using OS mutexes and a RAM-only frame.

The producer holds a named mutex while owning VideoCapture. Other clients only
read the latest complete frame. Closing/crashing the producer lets another
client take ownership; no helper service, socket, image file or network port.
"""
import ctypes
from ctypes import wintypes
import mmap
import struct
import time
import cv2
import numpy as np

WIDTH, HEIGHT = 640, 360
HEADER = struct.Struct("<QdIII")
OFFSET = 64
SIZE = OFFSET + WIDTH * HEIGHT * 3


class SharedCamera:
    def __init__(self, index=0, namespace="PeekerDeskVeil"):
        self.api = ctypes.WinDLL("kernel32", use_last_error=True)
        self.api.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
        self.api.CreateMutexW.restype = wintypes.HANDLE
        self.api.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        self.api.WaitForSingleObject.restype = wintypes.DWORD
        self.api.ReleaseMutex.argtypes = [wintypes.HANDLE]
        self.api.CloseHandle.argtypes = [wintypes.HANDLE]
        name = f"Local\\{namespace}.camera.{index}"
        self.owner = self.api.CreateMutexW(None, False, name + ".owner")
        self.frame_lock = self.api.CreateMutexW(None, False, name + ".frame")
        if not self.owner or not self.frame_lock:
            if self.owner:
                self.api.CloseHandle(self.owner)
            if self.frame_lock:
                self.api.CloseHandle(self.frame_lock)
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            self.memory = mmap.mmap(-1, SIZE, tagname=name + ".pixels")
        except Exception:
            self.api.CloseHandle(self.owner)
            self.api.CloseHandle(self.frame_lock)
            raise
        self.index = index
        self.camera = None
        self.producer = False
        self.closed = False
        self.pending = False
        self.timestamp = None
        self.last_sequence = 0
        self.just_opened = False

    def isOpened(self):
        return not self.closed

    def _acquire_frame(self):
        result = self.api.WaitForSingleObject(self.frame_lock, 100)
        if result == 0x80:  # Writer died; discard any incomplete frame.
            self.memory[:HEADER.size] = bytes(HEADER.size)
        return result in (0, 0x80)

    def _clear(self):
        if self._acquire_frame():
            try:
                self.memory[:HEADER.size] = bytes(HEADER.size)
            finally:
                self.api.ReleaseMutex(self.frame_lock)

    def _become_producer(self):
        if self.producer:
            return True
        if self.api.WaitForSingleObject(self.owner, 0) not in (0, 0x80):
            return False
        self.producer = True
        self.just_opened = True
        self._clear()
        self.camera = cv2.VideoCapture(self.index, cv2.CAP_DSHOW)
        if self.camera.isOpened():
            self.camera.set(cv2.CAP_PROP_FRAME_WIDTH, WIDTH)
            self.camera.set(cv2.CAP_PROP_FRAME_HEIGHT, HEIGHT)
            self.camera.set(cv2.CAP_PROP_FPS, 30)
        return True

    def read(self):
        self.pending = False
        self.just_opened = False
        self.timestamp = None
        if self.closed:
            return False, None
        deadline = time.monotonic() + .25
        while True:
            if self._become_producer():
                if not self.camera.isOpened():
                    return False, None
                captured = time.monotonic()
                ok, frame = self.camera.read()
                if not ok or frame is None:
                    self._clear()
                    return False, None
                h, w = frame.shape[:2]
                scale = min(1., WIDTH / w, HEIGHT / h)
                if scale < 1:
                    frame = cv2.resize(frame, (round(w * scale), round(h * scale)), interpolation=cv2.INTER_AREA)
                frame = np.ascontiguousarray(frame)
                h, w = frame.shape[:2]
                if self._acquire_frame():
                    try:
                        data = frame.tobytes()
                        self.memory[OFFSET:OFFSET + len(data)] = data
                        self.memory[:HEADER.size] = HEADER.pack(time.monotonic_ns(), captured, w, h, len(data))
                    finally:
                        self.api.ReleaseMutex(self.frame_lock)
                self.timestamp = captured
                return True, frame
            if self._acquire_frame():
                try:
                    sequence, captured, w, h, length = HEADER.unpack(self.memory[:HEADER.size])
                    if (sequence and sequence != self.last_sequence and 0 < w <= WIDTH and 0 < h <= HEIGHT
                            and length == w * h * 3 and 0 <= time.monotonic() - captured <= .8):
                        frame = np.frombuffer(self.memory[OFFSET:OFFSET + length], dtype=np.uint8).reshape(h, w, 3).copy()
                        self.last_sequence = sequence
                        self.timestamp = captured
                        return True, frame
                finally:
                    self.api.ReleaseMutex(self.frame_lock)
            if time.monotonic() >= deadline:
                self.pending = True
                return False, None
            time.sleep(.005)

    def release(self):
        if self.closed:
            return
        try:
            if self.producer:
                try:
                    if self.camera is not None:
                        self.camera.release()
                    self._clear()
                finally:
                    self.api.ReleaseMutex(self.owner)
                    self.producer = False
        finally:
            self.memory.close()
            self.api.CloseHandle(self.frame_lock)
            self.api.CloseHandle(self.owner)
            self.closed = True
