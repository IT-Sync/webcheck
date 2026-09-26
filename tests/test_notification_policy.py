import unittest
from datetime import datetime, timedelta

from bot.core.notification_policy import reminder_kind


class NotificationPolicyTest(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 9, 26, 12, 0)
        self.preferences = {"repeat_minutes": 30, "prolonged_minutes": 60}
        self.incident = {
            "started_at": self.now - timedelta(minutes=90),
            "acknowledged_at": None,
            "last_reminder_at": None,
            "prolonged_notified_at": None,
        }

    def test_prolonged_notification_has_priority_and_fires_once(self):
        self.assertEqual(
            reminder_kind(
                self.now, self.incident, self.preferences,
                self.now - timedelta(minutes=45),
            ),
            "prolonged",
        )
        self.incident["prolonged_notified_at"] = self.now - timedelta(minutes=1)
        self.assertEqual(
            reminder_kind(
                self.now, self.incident, self.preferences,
                self.now - timedelta(minutes=45),
            ),
            "repeat",
        )

    def test_acknowledgement_suppresses_all_reminders(self):
        self.incident["acknowledged_at"] = self.now - timedelta(minutes=5)
        self.assertIsNone(reminder_kind(
            self.now, self.incident, self.preferences,
            self.now - timedelta(hours=1),
        ))

    def test_repeat_waits_for_configured_interval(self):
        self.incident["prolonged_notified_at"] = self.now
        self.assertIsNone(reminder_kind(
            self.now, self.incident, self.preferences,
            self.now - timedelta(minutes=29),
        ))
        self.assertEqual(reminder_kind(
            self.now, self.incident, self.preferences,
            self.now - timedelta(minutes=30),
        ), "repeat")


if __name__ == "__main__":
    unittest.main()
