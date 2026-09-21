import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import unittest
from PySide6.QtCore import QObject, QRect, Signal, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from ui.veil import VeilManager, VeilWindow

app = QApplication.instance() or QApplication([])


class Screen(QObject):
    geometryChanged = Signal(QRect)

    def __init__(self, rect):
        super().__init__()
        self.rect = rect

    def geometry(self):
        return self.rect


class Displays(QObject):
    screenAdded = Signal(object)
    screenRemoved = Signal(object)

    def __init__(self):
        super().__init__()
        self.items = [Screen(QRect(0, 0, 1280, 720)), Screen(QRect(-1920, 0, 1920, 1080))]

    def screens(self):
        return self.items


class VeilTests(unittest.TestCase):
    def setUp(self):
        self.displays = Displays()
        self.manager = VeilManager(self.displays)

    def tearDown(self):
        for screen in list(self.manager.windows):
            self.manager.remove_screen(screen)
        app.processEvents()

    def test_all_screens_and_mouse_flags(self):
        self.manager.set_covered(True, immediate=True)
        self.assertEqual(len(self.manager.windows), 2)
        for screen, window in self.manager.windows.items():
            self.assertTrue(window.isVisible())
            self.assertEqual(window.geometry(), screen.geometry())
            self.assertEqual(window.windowOpacity(), 1.)
            self.assertTrue(window.windowFlags() & Qt.WindowType.WindowDoesNotAcceptFocus)
            self.assertFalse(window.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents))
            QTest.mouseClick(window, Qt.MouseButton.LeftButton)
            self.assertTrue(window.isVisible())

    def test_hotplug_is_immediately_opaque_and_removable(self):
        self.manager.set_covered(True, immediate=True)
        screen = Screen(QRect(1280, -200, 800, 600))
        self.displays.screenAdded.emit(screen)
        window = self.manager.windows[screen]
        self.assertTrue(window.isVisible())
        self.assertEqual(window.windowOpacity(), 1.)
        screen.rect = QRect(1400, 0, 1024, 768)
        screen.geometryChanged.emit(screen.rect)
        self.assertEqual(window.geometry(), screen.rect)
        self.displays.screenRemoved.emit(screen)
        self.assertNotIn(screen, self.manager.windows)

    def test_fade_reversal_and_emergency_hide(self):
        self.manager.set_covered(True)
        QTest.qWait(250)
        self.manager.set_covered(False)
        QTest.qWait(60)
        self.manager.set_covered(True)
        QTest.qWait(250)
        for window in self.manager.windows.values():
            self.assertTrue(window.isVisible())
            self.assertEqual(window.windowOpacity(), 1.)
        self.manager.set_covered(False, immediate=True)
        for window in self.manager.windows.values():
            self.assertFalse(window.isVisible())
            self.assertTrue(window.background.isNull())


if __name__ == "__main__":
    unittest.main()
