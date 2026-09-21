from pathlib import Path
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QIcon

app = QApplication([])
root = Path(__file__).resolve().parents[1]
icon = QIcon(str(root / "assets/tray.svg"))
if not icon.pixmap(64, 64).save(str(root / "assets/deskveil.ico"), "ICO"):
    raise RuntimeError("Could not write Windows icon")
