import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from bot.webapp.validation import TargetValidationError, is_public_address, validate_monitoring_target


class WebAppTargetValidationTest(unittest.TestCase):
    def test_accepts_public_addresses(self):
        self.assertTrue(is_public_address("8.8.8.8"))
        self.assertTrue(is_public_address("2001:4860:4860::8888"))

    def test_rejects_non_public_addresses(self):
        for address in (
            "127.0.0.1",
            "10.0.0.1",
            "172.16.0.1",
            "192.168.1.1",
            "169.254.169.254",
            "::1",
            "not-an-ip",
        ):
            with self.subTest(address=address):
                self.assertFalse(is_public_address(address))

    def test_dns_lookup_timeout_is_reported(self):
        with patch("bot.webapp.validation.asyncio.to_thread", AsyncMock(side_effect=TimeoutError)):
            with self.assertRaisesRegex(TargetValidationError, "слишком долго"):
                asyncio.run(validate_monitoring_target("example.com"))


if __name__ == "__main__":
    unittest.main()
