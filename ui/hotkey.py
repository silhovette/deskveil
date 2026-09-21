"""Windows global emergency shortcut; registered before monitoring can start."""
import ctypes
import logging
from ctypes import wintypes
from PySide6.QtCore import QAbstractNativeEventFilter


class EmergencyHotkey(QAbstractNativeEventFilter):
    ID = 0x4456
    REVEAL_ID = 0x4457

    def __init__(self, app, callback, reveal_callback=None):
        super().__init__()
        self.app, self.callback = app, callback
        self.reveal_callback = reveal_callback
        self.reveal_registered = False
        self.covered = False
        # MOD_ALT | MOD_CONTROL | MOD_SHIFT | MOD_NOREPEAT
        self.registered = bool(ctypes.windll.user32.RegisterHotKey(None, self.ID, 0x4007, ord("V")))
        if not self.registered:
            raise RuntimeError("Ctrl + Alt + Shift + V is already in use. Close the other DeskVeil instance or free this shortcut.")
        app.installNativeEventFilter(self)

    def set_covered(self, covered):
        if covered == self.covered:
            return
        self.covered = covered
        if covered and self.reveal_callback:
            self.reveal_registered = bool(ctypes.windll.user32.RegisterHotKey(
                None, self.REVEAL_ID, 0x4002, ord("V")))  # CTRL | NOREPEAT
            if not self.reveal_registered:
                logging.getLogger("deskveil").warning("Ctrl+V unavailable; emergency shortcut remains active")
        elif self.reveal_registered:
            ctypes.windll.user32.UnregisterHotKey(None, self.REVEAL_ID)
            self.reveal_registered = False

    def nativeEventFilter(self, event_type, message):
        msg = wintypes.MSG.from_address(int(message))
        if msg.message == 0x0312 and msg.wParam == self.ID:
            self.callback()
            return True, 0
        if msg.message == 0x0312 and msg.wParam == self.REVEAL_ID and self.reveal_registered:
            self.reveal_callback()
            return True, 0
        return False, 0

    def close(self):
        self.set_covered(False)
        if self.registered:
            ctypes.windll.user32.UnregisterHotKey(None, self.ID)
            self.app.removeNativeEventFilter(self)
            self.registered = False
