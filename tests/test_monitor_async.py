import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from bot.checks import monitor


class MonitorAsyncIoTest(unittest.TestCase):
    def test_ssl_socket_work_runs_outside_event_loop(self):
        to_thread = AsyncMock(return_value=42)

        with patch.object(monitor.asyncio, "to_thread", to_thread):
            result = asyncio.run(monitor.check_ssl("https://example.com"))

        self.assertEqual(result, 42)
        to_thread.assert_awaited_once_with(
            monitor._check_ssl_sync,
            "https://example.com",
        )


if __name__ == "__main__":
    unittest.main()
