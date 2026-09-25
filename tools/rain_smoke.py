"""Native Rain/controller regression test. Briefly covers screens; always reveals."""
import ctypes
from ctypes import wintypes
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QSettings, QTimer
from PySide6.QtWidgets import QApplication
from tools.windows_smoke import FakeCamera
from tools.live_glass_smoke import Animation, wait_events
from detection.presence_engine import State
import main


def run():
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    api = ctypes.windll.user32
    api.GetForegroundWindow.restype = wintypes.HWND
    api.GetWindowDisplayAffinity.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    api.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    api.WindowFromPoint.argtypes = [wintypes.POINT]
    api.WindowFromPoint.restype = wintypes.HWND
    api.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
    api.GetAncestor.restype = wintypes.HWND
    scenes = []
    for screen in app.screens():
        scene = Animation()
        scene.setGeometry(screen.geometry())
        scene.show()
        scenes.append(scene)
    scenes[0].activateWindow()
    wait_events(200)
    foreground = api.GetForegroundWindow()
    with tempfile.TemporaryDirectory() as folder:
        settings = QSettings(str(Path(folder)/'settings.ini'), QSettings.Format.IniFormat)
        with patch.object(main, 'CameraWorker', FakeCamera), patch.object(main, 'QSettings', lambda *_: settings):
            controller = main.Controller(app)
        controller.timer.stop()
        QTimer.singleShot(20000, controller.shutdown)
        try:
            wait_events(100)
            windows = list(controller.veils.windows.values())
            assert all(w.rain is None for w in windows)
            controller.tray.rain_action.trigger()
            assert controller.tray.rain_action.isChecked()
            assert settings.value('appearance/rain', False, type=bool)
            assert all(w.rain_enabled and not w.rain.timer.isActive() for w in windows)
            # Automatic absence -> normal fade in; stable presence -> fade out.
            now = time.monotonic()
            for i in range(11):
                controller.engine.update(False, now+i*.2)
            controller.render()
            for _ in range(60):
                wait_events(50)
                if all(w.isVisible() and w.rain.frames > 3 and not w.animation.isActive() for w in windows):
                    break
            assert controller.engine.covered
            for w in windows:
                assert w.rain.isValid() and not w.rain.broken
                assert w.rain.frames > 3 and w.rain.timer.isActive()
                assert abs(w.windowOpacity()-w.cover_opacity) < .005
                assert w.live_capture
                affinity = wintypes.DWORD()
                assert api.GetWindowDisplayAffinity(int(w.winId()), ctypes.byref(affinity))
                assert affinity.value == 0x11, 'Rain lost capture exclusion'
                rect = wintypes.RECT()
                api.GetWindowRect(int(w.winId()), ctypes.byref(rect))
                point = wintypes.POINT((rect.left+rect.right)//2, rect.bottom-2)
                assert api.GetAncestor(api.WindowFromPoint(point), 2) == int(w.winId())
            assert api.GetForegroundWindow() == foreground, ('Rain took focus', foreground,
                    api.GetForegroundWindow(), [(int(w.winId()),int(w.rain.winId())) for w in windows])
            before = [w.rain.frames for w in windows]
            measured_at = time.perf_counter()
            background_uploads = [w.rain.uploads for w in windows]
            colors = set()
            for _ in range(15):
                wait_events(100)
                background = windows[0].background
                c = background.pixelColor(background.width()//2, background.height()//2)
                colors.add('red' if c.red() > c.blue() else 'blue')
            assert colors == {'red','blue'}, (colors, [s.frames for s in scenes],
                    [(w.rain.frames, w.rain.uploads, w.live_capture,
                      w.background.pixelColor(0,0).getRgb(), w.capture.request) for w in windows])
            assert all(w.rain.frames > f+40 for w,f in zip(windows,before))
            assert all(w.rain.uploads > u for w,u in zip(windows,background_uploads))
            print('Rain FPS with changing live background:',
                  [round((w.rain.frames-f)/(time.perf_counter()-measured_at),1) for w,f in zip(windows,before)])
            pointer = wintypes.POINT(); api.GetCursorPos(ctypes.byref(pointer))
            api.mouse_event(1, 20, 20, 0, 0)
            api.mouse_event(2, 0, 0, 0, 0); api.mouse_event(4, 0, 0, 0, 0)
            api.mouse_event(0x800, 0, 0, 120, 0)
            wait_events(70)
            after = wintypes.POINT(); api.GetCursorPos(ctypes.byref(after))
            assert (pointer.x,pointer.y) == (after.x,after.y)
            assert all(scene.inputs == 0 for scene in scenes)
            controller.engine.update(True, now+2.2)
            controller.engine.update(True, now+2.5)
            controller.engine.update(True, now+2.7)
            controller.render()
            wait_events(350)
            assert controller.engine.state == State.PRESENT
            stopped = [w.rain.frames for w in windows]
            wait_events(150)
            assert all(not w.isVisible() and not w.rain.timer.isActive() and w.rain.texture is None
                       and w.rain.frames == f for w,f in zip(windows,stopped))
            assert controller.veils.cursor.hook is None
            # Disable while covered, then enable again on an existing HWND.
            controller.cover_now(); wait_events(750)
            controller.tray.rain_action.trigger(); wait_events(120)
            assert all(w.isVisible() and not w.rain.active and not w.rain.isVisible() for w in windows)
            assert controller.engine.covered and controller.veils.cursor.hook
            controller.tray.rain_action.trigger(); wait_events(350)
            assert all(w.rain.active and w.rain.isVisible() and not w.rain.broken for w in windows)
            api.PostThreadMessageW.argtypes = [wintypes.DWORD,wintypes.UINT,wintypes.WPARAM,wintypes.LPARAM]
            thread_id = ctypes.windll.kernel32.GetCurrentThreadId()
            assert api.PostThreadMessageW(thread_id, 0x0312, controller.hotkey.REVEAL_ID, 0)
            wait_events(100)
            assert controller.engine.state == State.PRESENT and controller.engine.snoozed_until is None
            controller.cover_now(); wait_events(400)
            assert api.PostThreadMessageW(thread_id, 0x0312, controller.hotkey.ID, 0)
            wait_events(100)
            assert controller.engine.state == State.SNOOZED
            assert all(not w.rain.timer.isActive() and not w.isVisible() for w in windows)
            assert controller.tray.rain_action.isChecked()
            controller.resume()
            controller.cover_now(); wait_events(400)
            controller.tray.enabled_action.trigger(); wait_events(100)
            assert not controller.enabled and controller.tray.isVisible()
            assert all(not w.rain.active for w in windows)
            controller.tray.enabled_action.trigger()
            # First GL child added while visible must keep the raster HWND.
            controller.tray.rain_action.trigger()
            controller.cover_now(); wait_events(400)
            for screen in list(controller.veils.windows):
                controller.veils.remove_screen(screen)
                controller.veils.add_screen(screen)
            wait_events(500)
            windows = list(controller.veils.windows.values())
            handles = [int(w.winId()) for w in windows]
            controller.tray.rain_action.trigger(); wait_events(500)
            assert all(w.rain.isValid() and w.live_capture for w in windows)
            assert handles == [int(w.winId()) for w in windows], 'Enabling Rain recreated a fullscreen window'
            assert api.GetForegroundWindow() == foreground
            windows[0].rain.fail('Injected renderer failure for fallback test')
            wait_events(100)
            assert not controller.tray.rain_action.isChecked()
            assert controller.engine.covered and all(w.isVisible() and not w.rain.active for w in windows)
            controller.tray.rain_action.trigger(); wait_events(100)
            assert not controller.tray.rain_action.isChecked(), 'Failed renderer left a misleading checked menu'
            controller.shutdown(); wait_events(200)
            assert all(not w.rain.timer.isActive() and not w.isVisible() for w in windows)
            assert controller.veils.cursor.hook is None
            assert not controller.thread.isRunning()
            print(f'PASS: Rain, automatic/manual cover, stable return, fades, toggles, live background, '
                  f'capture exclusion, taskbar, mouse blocking, focus, snooze, pause and shutdown; {len(windows)} display(s).')
        finally:
            controller.shutdown()
            controller.thread.wait(3000)
            controller.veils.shutdown()
            controller.hotkey.close()
            for scene in scenes:
                scene.close()
    return 0


if __name__ == '__main__':
    sys.exit(run())
