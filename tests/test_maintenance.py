import unittest
from unittest.mock import Mock, patch

from bot.infra.maintenance import (
    MaintenanceSettings,
    _archive_hourly_batch,
    _require_cleanup_index,
    run_database_maintenance,
)


class MaintenanceSettingsTest(unittest.TestCase):
    def test_defaults_are_safe_and_cleanup_is_opt_in(self):
        with patch.dict("os.environ", {}, clear=True):
            settings = MaintenanceSettings.from_env()

        self.assertFalse(settings.enabled)
        self.assertEqual(settings.agent_result_days, 7)
        self.assertEqual(settings.agent_hourly_days, 30)
        self.assertEqual(settings.user_log_days, 90)
        self.assertEqual(settings.event_days, 365)
        self.assertEqual(settings.batch_size, 5000)

    def test_batch_settings_are_bounded(self):
        with patch.dict(
            "os.environ",
            {"DB_CLEANUP_BATCH_SIZE": "999999", "DB_CLEANUP_MAX_BATCHES": "0"},
            clear=True,
        ):
            settings = MaintenanceSettings.from_env()

        self.assertEqual(settings.batch_size, 50000)
        self.assertEqual(settings.max_batches, 1)

    @patch("bot.infra.maintenance._connect")
    def test_disabled_maintenance_does_not_connect(self, connect):
        settings = MaintenanceSettings(False, 7, 90, 90, 365, 5000, 10)

        result = run_database_maintenance(settings=settings)

        self.assertEqual(result, {"enabled": False, "deleted": {}})
        connect.assert_not_called()

    def test_cleanup_rejects_an_invalid_index(self):
        cursor = Mock()
        cursor.fetchone.return_value = (False,)

        with self.assertRaisesRegex(RuntimeError, "valid idx_agent"):
            _require_cleanup_index(cursor)

    def test_cleanup_accepts_a_valid_ready_index(self):
        cursor = Mock()
        cursor.fetchone.return_value = (True,)

        _require_cleanup_index(cursor)


    def test_hourly_rows_roll_up_into_daily_aggregates(self):
        cursor = Mock()
        cursor.rowcount = 4

        count = _archive_hourly_batch(cursor, "cutoff", 500)

        self.assertEqual(count, 4)
        query, params = cursor.execute.call_args.args
        self.assertIn("INSERT INTO agent_check_daily", query)
        self.assertIn("date_trunc('day', bucket_start)", query)
        self.assertIn("DELETE FROM agent_check_hourly", query)
        self.assertEqual(params, ("cutoff", 500))

if __name__ == "__main__":
    unittest.main()
