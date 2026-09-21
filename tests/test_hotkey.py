import unittest
from unittest.mock import Mock, patch
from ui.hotkey import EmergencyHotkey


class HotkeyTests(unittest.TestCase):
    def test_ctrl_v_is_reserved_only_while_covered(self):
        with patch("ui.hotkey.ctypes.windll.user32") as api:
            api.RegisterHotKey.return_value = 1
            hotkey = EmergencyHotkey(Mock(), Mock(), Mock())
            self.assertEqual(api.RegisterHotKey.call_count, 1)
            hotkey.set_covered(True)
            api.RegisterHotKey.assert_called_with(None, hotkey.REVEAL_ID, 0x4002, ord("V"))
            hotkey.set_covered(True)
            self.assertEqual(api.RegisterHotKey.call_count, 2)
            hotkey.set_covered(False)
            api.UnregisterHotKey.assert_called_with(None, hotkey.REVEAL_ID)
            self.assertFalse(hotkey.reveal_registered)
            hotkey.close()

    def test_ctrl_v_conflict_preserves_emergency_shortcut(self):
        with patch("ui.hotkey.ctypes.windll.user32") as api:
            api.RegisterHotKey.side_effect = [1, 0]
            hotkey = EmergencyHotkey(Mock(), Mock(), Mock())
            hotkey.set_covered(True)
            self.assertFalse(hotkey.reveal_registered)
            self.assertTrue(hotkey.registered)
            hotkey.close()
