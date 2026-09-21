"""Optional live view. Holds only the latest in-memory image and face boxes."""
from PySide6.QtCore import Qt, QRectF, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QIcon
from PySide6.QtWidgets import QWidget
import config


class CameraPreview(QWidget):
    closed = Signal()

    def __init__(self):
        super().__init__()
        self.setWindowTitle("DeskVeil · Camera Preview")
        self.setWindowIcon(QIcon(str(config.resource_path("assets/tray.svg"))))
        self.resize(config.PREVIEW_WIDTH, config.PREVIEW_HEIGHT)
        self.setMinimumSize(320, 240)
        self.image = QImage()
        self.boxes = ()
        self.message = "Starting camera…"

    def set_frame(self, image, boxes):
        self.image = image
        self.boxes = boxes
        self.update()

    def clear_frame(self, message="Starting camera…"):
        self.image = QImage()
        self.boxes = ()
        self.message = message
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#14191f"))
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        viewport = QRectF(self.rect()).adjusted(12, 12, -12, -42)
        if self.image.isNull():
            painter.setPen(QColor("#dce3eb"))
            painter.drawText(viewport, Qt.AlignmentFlag.AlignCenter, self.message)
        else:
            scale = min(viewport.width() / self.image.width(), viewport.height() / self.image.height())
            width, height = self.image.width() * scale, self.image.height() * scale
            target = QRectF(viewport.center().x() - width / 2, viewport.center().y() - height / 2, width, height)
            painter.drawImage(target, self.image)
            painter.setPen(QPen(QColor("#5ce5aa"), 2))
            for x1, y1, x2, y2 in self.boxes:
                painter.drawRect(QRectF(target.x() + x1 * width, target.y() + y1 * height,
                                        (x2 - x1) * width, (y2 - y1) * height))
        painter.setPen(QColor("#aab6c5"))
        count = len(self.boxes)
        text = f"{count} face{'s' if count != 1 else ''} detected" if not self.image.isNull() else ""
        painter.drawText(QRectF(12, self.height() - 34, self.width() - 24, 26), Qt.AlignmentFlag.AlignCenter, text)

    def closeEvent(self, event):
        self.clear_frame()
        self.closed.emit()
        super().closeEvent(event)

