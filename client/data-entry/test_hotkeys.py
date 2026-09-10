import unittest

from hotkeys import _mac_virtual_key, _parse_hotkey, _windows_virtual_key


class HotkeyParsingTests(unittest.TestCase):
    def test_parses_and_normalizes_modifier_aliases(self):
        self.assertEqual(
            _parse_hotkey("Shift+Control+A"),
            (("ctrl", "shift"), "a"),
        )

    def test_rejects_missing_regular_key(self):
        with self.assertRaisesRegex(ValueError, "一个普通按键"):
            _parse_hotkey("Ctrl+Shift")

    def test_rejects_multiple_regular_keys(self):
        with self.assertRaisesRegex(ValueError, "一个普通按键"):
            _parse_hotkey("Ctrl+A+B")

    def test_maps_supported_platform_keys(self):
        self.assertEqual(_windows_virtual_key("3"), ord("3"))
        self.assertEqual(_windows_virtual_key("f12"), 0x7B)
        self.assertEqual(_mac_virtual_key("3"), 20)
        self.assertEqual(_mac_virtual_key("f12"), 111)


if __name__ == "__main__":
    unittest.main()
