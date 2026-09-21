from PySide6.QtCore import Signal
from PySide6.QtGui import QIcon, QCursor
from PySide6.QtWidgets import QMenu, QSystemTrayIcon
import config


class Tray(QSystemTrayIcon):
    enabled_requested = Signal(bool)
    cover_requested = Signal()
    snooze_requested = Signal()
    resume_requested = Signal()
    preview_requested = Signal()
    exit_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.icons = {name: QIcon(str(config.resource_path("assets/" + name)))
                      for name in ("tray.svg", "tray_disabled.svg", "tray_error.svg")}
        self.menu = QMenu()
        self.enabled_action = self.menu.addAction("启用 DeskVeil")
        self.enabled_action.setCheckable(True)
        self.enabled_action.setChecked(True)
        self.enabled_action.triggered.connect(lambda checked: self.enabled_requested.emit(checked))
        self.cover_action = self.menu.addAction("Cover Now", self.cover_requested.emit)
        self.snooze_action = self.menu.addAction("Snooze for 10 min", self.snooze_requested.emit)
        self.resume_action = self.menu.addAction("Resume Monitoring", self.resume_requested.emit)
        self.resume_action.setVisible(False)
        self.preview_action = self.menu.addAction("Camera Preview", self.preview_requested.emit)
        self.menu.addSeparator()
        self.menu.addAction("Exit", self.exit_requested.emit)
        self.setContextMenu(self.menu)
        self.activated.connect(self.on_activated)
        self.set_status("Starting…")

    def on_activated(self, reason):
        # Qt opens the assigned context menu for right clicks. Open the same
        # menu on left clicks without executing a second blocking event loop.
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.menu.popup(QCursor.pos())

    def set_status(self, text, snoozed=False, error=False, enabled=True):
        asset = "tray_error.svg" if error else "tray_disabled.svg" if snoozed or not enabled else "tray.svg"
        self.setIcon(self.icons[asset])
        self.setToolTip("DeskVeil · " + text + "\nReveal while covered: Ctrl + V\nReveal + snooze: Ctrl + Alt + Shift + V")
        self.enabled_action.setChecked(enabled)
        self.cover_action.setEnabled(enabled)
        self.preview_action.setEnabled(enabled)
        self.resume_action.setVisible(enabled and snoozed)
        self.snooze_action.setVisible(enabled and not snoozed)
