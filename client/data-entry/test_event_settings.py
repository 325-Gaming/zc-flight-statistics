import unittest

from event_settings import compose_event_name


class EventSettingsTests(unittest.TestCase):
    def test_compose_event_name(self):
        self.assertEqual(
            compose_event_name("Zc航空", "石白深蓝之夜"),
            "Zc航空-石白深蓝之夜",
        )

    def test_compose_event_name_requires_event_name(self):
        with self.assertRaisesRegex(ValueError, "活动名称不能为空"):
            compose_event_name("", "石白深蓝之夜")

    def test_compose_event_name_requires_pool_name(self):
        with self.assertRaisesRegex(ValueError, "卡池名称不能为空"):
            compose_event_name("Zc航空", "")


if __name__ == "__main__":
    unittest.main()
