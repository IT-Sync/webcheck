import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from bot.core.content_checks import evaluate_response, normalize_check_settings
from bot.checks.service import check_resource
from bot.core.target_validation import TargetValidationError, resolve_public_addresses


class ContentCheckSettingsTest(unittest.TestCase):
    def test_normalizes_status_text_and_json_assertions(self):
        settings = normalize_check_settings({
            "expected_status_codes": [204, "200", 204],
            "required_text": " healthy ",
            "json_assertions": {"data.items[0].state": "ready"},
        })

        self.assertEqual(settings["expected_status_codes"], [200, 204])
        self.assertEqual(settings["required_text"], "healthy")
        self.assertEqual(
            evaluate_response(
                200,
                '{"message":"healthy","data":{"items":[{"state":"ready"}]}}',
                settings,
            ),
            None,
        )

    def test_reports_each_assertion_failure(self):
        self.assertIn(
            "ожидался",
            evaluate_response(503, "", {
                "expected_status_codes": [200],
                "required_text": None,
                "json_assertions": {},
            }),
        )
        self.assertIn(
            "обязательный текст",
            evaluate_response(200, "not ready", {
                "expected_status_codes": [200],
                "required_text": "healthy",
                "json_assertions": {},
            }),
        )
        self.assertIn(
            "не совпадает",
            evaluate_response(200, '{"status":"down"}', {
                "expected_status_codes": [200],
                "required_text": None,
                "json_assertions": {"status": "ok"},
            }),
        )

    def test_rejects_invalid_status_and_json_path(self):
        with self.assertRaises(ValueError):
            normalize_check_settings({"expected_status_codes": [99]})
        with self.assertRaises(ValueError):
            normalize_check_settings({"expected_status_codes": [200.5]})
        with self.assertRaises(ValueError):
            normalize_check_settings({"json_assertions": {"items..state": "ok"}})


class PublicCheckTargetTest(unittest.TestCase):
    def test_check_path_rejects_any_private_resolution(self):
        with patch(
            "bot.core.target_validation.asyncio.to_thread",
            AsyncMock(return_value=["8.8.8.8", "127.0.0.1"]),
        ):
            with self.assertRaises(TargetValidationError):
                asyncio.run(resolve_public_addresses("https://example.com"))


    def test_unsafe_check_target_skips_followup_socket_checks(self):
        http = {"ok": False, "target_validation_failed": True, "error": "private"}
        ssl_check = AsyncMock()
        domain_check = AsyncMock()
        with patch("bot.checks.service.check_http_details", AsyncMock(return_value=http)), \
                patch("bot.checks.service.check_ssl", ssl_check), \
                patch("bot.checks.service.check_domain_expiry", domain_check):
            result = asyncio.run(check_resource("https://example.com"))

        self.assertFalse(result.http["ok"])
        self.assertEqual(result.ssl_days, -1)
        ssl_check.assert_not_awaited()
        domain_check.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
