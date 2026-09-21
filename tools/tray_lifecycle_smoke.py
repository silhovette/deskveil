"""Exercise the real tray menu and camera pause/resume through mouse clicks."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
import main


def run():
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    controller = main.Controller(app)
    failures = []
    finished = []

    def checked(fn):
        def wrapped():
            try:
                fn()
            except Exception as error:
                import traceback
                traceback.print_exc()
                failures.append(str(error))
                controller.shutdown()
        return wrapped

    def click_toggle():
        menu = controller.tray.menu
        menu.popup(app.primaryScreen().availableGeometry().center())
        QTest.mouseClick(menu, Qt.MouseButton.LeftButton,
                         pos=menu.actionGeometry(controller.tray.enabled_action).center())

    def disable():
        print('before:', controller.tray.isVisible(), controller.tray.geometry(), flush=True)
        click_toggle()
        QTimer.singleShot(1500, checked(verify_disabled))

    def verify_disabled():
        assert not controller.enabled
        assert controller.tray.isVisible()
        assert controller.thread.isRunning() and not controller.closing
        assert controller.worker.camera is None and not controller.worker.enabled
        print('paused:', controller.tray.isVisible(), controller.tray.geometry(), flush=True)
        click_toggle()
        QTimer.singleShot(1500, checked(verify_enabled))

    def verify_enabled():
        assert controller.enabled and controller.tray.isVisible()
        assert controller.worker.enabled and controller.thread.isRunning()
        assert not controller.closing
        print('resumed:', controller.tray.isVisible(), controller.tray.geometry(), flush=True)
        finished.append(True)
        controller.shutdown()

    QTimer.singleShot(2000, checked(disable))
    QTimer.singleShot(10000, controller.shutdown)
    app.exec()
    assert finished and not failures, failures
    print('PASS: real menu clicks pause and resume while the app and tray remain alive')


if __name__ == '__main__':
    run()
