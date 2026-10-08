"""Check passenger hotkeys without registering native OS shortcuts."""

import unittest
from unittest.mock import Mock, patch

from test_webview_gate import _load_app_module


class PassengerHotkeyTests(unittest.TestCase):
    def test_navigation_callbacks_use_the_same_actions_as_buttons(self):
        module = _load_app_module()
        app = module.WebViewApp.__new__(module.WebViewApp)
        app.action = Mock()
        app._predict = Mock()
        hotkeys = dict.fromkeys(module.HOTKEY_KEYS, "")
        hotkeys.update(hotkey_previous_user="Q", hotkey_next_user="E")
        with patch.object(module.sys, "platform", "win32"), \
                patch.object(module, "register_hotkeys") as register:
            app._register_hotkeys(hotkeys)
        callbacks = register.call_args.args[0]
        callbacks["Q"]()
        callbacks["E"]()
        self.assertEqual(app.action.call_args_list, [
            unittest.mock.call("main", "previous", {}),
            unittest.mock.call("main", "next", {}),
        ])

    def test_empty_navigation_shortcuts_disable_registration(self):
        module = _load_app_module()
        app = module.WebViewApp.__new__(module.WebViewApp)
        app._predict = Mock()
        with patch.object(module, "register_hotkeys") as register:
            self.assertIsNone(app._register_hotkeys(dict.fromkeys(module.HOTKEY_KEYS, "")))
        register.assert_not_called()

    def test_navigation_shortcuts_cannot_duplicate_gacha_shortcuts(self):
        module = _load_app_module()
        app = module.WebViewApp.__new__(module.WebViewApp)
        app._predict = Mock()
        hotkeys = dict.fromkeys(module.HOTKEY_KEYS, "")
        hotkeys.update(hotkey_previous_user="3", hotkey_3x="3")
        with self.assertRaisesRegex(ValueError, "快捷键不能重复"):
            app._register_hotkeys(hotkeys)


if __name__ == "__main__":
    unittest.main()
