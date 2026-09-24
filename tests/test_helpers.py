import sys
import unittest
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bot"))

from callback_data import (
    admin_delete_callback,
    site_check_now_callback,
    site_delete_callback,
    site_history_callback,
    site_pause_callback,
    site_pause_1h_callback,
    site_resume_callback,
    site_status_callback,
)
from url_utils import normalize_url
from status_formatter import (
    append_agent_results,
    format_domain_expiry_alert,
    format_down_alert,
    format_recovery_alert,
    format_ssl_expiry_alert,
    format_status_text,
    format_weekly_user_report,
    format_weekly_user_report_chunks,
    split_message,
)


class UrlUtilsTest(unittest.TestCase):
    def test_normalize_plain_domain(self):
        self.assertEqual(normalize_url("Example.COM"), "https://example.com")

    def test_normalize_removes_www_and_path(self):
        self.assertEqual(
            normalize_url("https://www.Example.com/some/path?x=1"),
            "https://example.com",
        )

    def test_normalize_keeps_invalid_input_visible(self):
        self.assertEqual(normalize_url("not a url"), "https://not a url")


class CallbackDataTest(unittest.TestCase):
    def test_site_callbacks_are_short_and_stable(self):
        status = site_status_callback(123456789)
        delete = site_delete_callback(123456789)
        pause = site_pause_callback(123456789)
        resume = site_resume_callback(123456789)

        self.assertEqual(status, "st:123456789")
        self.assertEqual(delete, "del:123456789")
        self.assertEqual(pause, "pause:123456789")
        self.assertEqual(resume, "resume:123456789")
        self.assertLessEqual(len(status.encode()), 64)
        self.assertLessEqual(len(delete.encode()), 64)
        self.assertLessEqual(len(pause.encode()), 64)
        self.assertLessEqual(len(resume.encode()), 64)

    def test_admin_callback_is_short_and_stable(self):
        callback = admin_delete_callback(987654321)

        self.assertEqual(callback, "ad:987654321")
        self.assertLessEqual(len(callback.encode()), 64)

    def test_incident_callbacks_are_short_and_stable(self):
        callbacks = [
            site_check_now_callback(123),
            site_pause_1h_callback(123),
            site_history_callback(123),
        ]

        self.assertEqual(callbacks, ["chk:123", "p1h:123", "hist:123"])
        for callback in callbacks:
            self.assertLessEqual(len(callback.encode()), 64)


class StatusFormatterTest(unittest.TestCase):
    def test_extended_status_contains_http_ssl_and_domain(self):
        status = format_status_text(
            {
                "ok": True,
                "status_code": 200,
                "method": "HEAD",
                "url": "https://example.com",
                "latency_ms": 123,
            },
            ssl_days=30,
            domain_days=90,
            registrar="Example Registrar",
        )

        self.assertIn("HTTP: OK", status)
        self.assertIn("200", status)
        self.assertIn("123 ms", status)
        self.assertIn("SSL: 30 дней", status)
        self.assertIn("Домен: 90 дней", status)
        self.assertIn("Example Registrar", status)

    def test_down_alert_contains_reason_and_fail_count(self):
        alert = format_down_alert(
            "https://example.com",
            {
                "ok": False,
                "url": "https://example.com",
                "error": "HTTP 503",
                "attempts": 6,
                "ip": "203.0.113.20",
            },
            fail_count=2,
            incident_started_at=datetime(2026, 6, 29, 14, 32),
            last_success_at=datetime(2026, 6, 29, 14, 27),
        )

        self.assertIn("🚨 example.com недоступен", alert)
        self.assertIn("HTTP 503", alert)
        self.assertIn("Проверок подряд: 2", alert)
        self.assertIn("Начало инцидента: 14:32 UTC", alert)
        self.assertIn("Последний успешный ответ: 14:27 UTC", alert)
        self.assertIn("IP: 203.0.113.20", alert)

    def test_recovery_alert_contains_downtime_and_response(self):
        alert = format_recovery_alert(
            "https://api.example.com/health",
            {"status_code": 200, "latency_ms": 184},
            incident_started_at=datetime.utcnow(),
            display_name="api-prod",
        )

        self.assertIn("✅ api-prod восстановлен", alert)
        self.assertIn("Простой:", alert)
        self.assertIn("HTTP: 200", alert)
        self.assertIn("Время ответа: 184 мс", alert)

    def test_ssl_expiry_alert_contains_resource_url(self):
        alert = format_ssl_expiry_alert("https://api.example.com/health", 7)

        self.assertIn("SSL истекает через 7 дней", alert)
        self.assertIn("Ресурс: api.example.com", alert)
        self.assertIn("URL: https://api.example.com/health", alert)

    def test_domain_expiry_alert_contains_resource_url(self):
        alert = format_domain_expiry_alert(
            "https://example.com",
            7,
            registrar="Example Registrar",
            contact_url="https://registrar.example",
        )

        self.assertIn("Домен истекает через 7 дней", alert)
        self.assertIn("Ресурс: example.com", alert)
        self.assertIn("URL: https://example.com", alert)
        self.assertIn("Example Registrar", alert)

    def test_weekly_report_summarizes_resources(self):
        report = format_weekly_user_report([
            {
                "url": "https://ok.example",
                "last_status": "HTTP: OK | 200 | HEAD | 50 ms\nSSL: 30 дней до истечения\nДомен: 90 дней до окончания",
                "last_checked": None,
                "is_paused": False,
            },
            {
                "url": "https://down.example",
                "last_status": "HTTP: DOWN | причина: timeout",
                "last_checked": None,
                "is_paused": True,
            },
        ])

        self.assertIn("Всего ресурсов: 2", report)
        self.assertIn("На паузе: 1", report)
        self.assertIn("https://down.example", report)

    def test_weekly_report_distinguishes_planned_maintenance(self):
        report = format_weekly_user_report([{
            "url": "https://maintenance.example",
            "last_status": "HTTP: OK | 200",
            "last_checked": None,
            "is_paused": False,
            "is_maintenance": True,
            "maintenance_ends_at": datetime(2026, 9, 24, 12, 0),
            "maintenance_reason": "Database migration",
            "maintenance_count_7d": 1,
            "site_group": "Production",
            "tags": ["api", "critical"],
        }])

        self.assertIn("Плановое обслуживание сейчас: 1", report)
        self.assertIn("Плановых окон за 7 дней: 1", report)
        self.assertIn("Database migration", report)
        self.assertIn("теги: api, critical", report)

    def test_weekly_report_includes_compact_agent_results(self):
        report = format_weekly_user_report([
            {
                "url": "https://glut1.ru",
                "last_status": (
                    "HTTP: OK | 200 | HEAD | 1293 ms | https://glut1.ru\n"
                    "SSL: 71 дней до истечения\n"
                    "Домен: 306 дней до окончания\n"
                    "🌍 Проверки агентами\n"
                    "• Earth [RU, Saint-Petersburg]\n"
                    "  HTTP: OK | 200 | HEAD | 115 ms | https://glut1.ru"
                ),
                "last_checked": datetime(2026, 7, 3, 11, 19, 36),
                "is_paused": False,
                "agent_results": [
                    {
                        "agent_id": "Earth",
                        "country": "RU",
                        "region": "Saint-Petersburg",
                        "http": {"ok": True, "latency_ms": 115},
                    },
                    {
                        "agent_id": "Mars",
                        "country": "RU",
                        "region": "Moscow",
                        "http": {"ok": True, "latency_ms": 107},
                    },
                ],
            },
        ])

        self.assertIn("Агенты: Earth [RU, Saint-Petersburg]: OK, 115 ms; Mars [RU, Moscow]: OK, 107 ms", report)
        self.assertNotIn("🌍 Проверки агентами", report)

    def test_weekly_report_chunks_limit_resources_per_message(self):
        rows = [
            {
                "url": f"https://site-{idx}.example",
                "last_status": "HTTP: OK | 200 | HEAD | 50 ms\nSSL: 30 дней до истечения\nДомен: 90 дней до окончания",
                "last_checked": None,
                "is_paused": False,
            }
            for idx in range(25)
        ]

        chunks = format_weekly_user_report_chunks(rows, per_message=10)

        self.assertEqual(len(chunks), 3)
        self.assertIn("Часть 1/3: ресурсы 1-10 из 25", chunks[0])
        self.assertIn("Часть 2/3: ресурсы 11-20 из 25", chunks[1])
        self.assertIn("Часть 3/3: ресурсы 21-25 из 25", chunks[2])
        self.assertEqual(chunks[0].count("https://site-"), 10)
        self.assertEqual(chunks[1].count("https://site-"), 10)
        self.assertEqual(chunks[2].count("https://site-"), 5)

    def test_split_message_keeps_chunks_under_limit(self):
        chunks = split_message("a\nb\nc", max_len=3)

        self.assertEqual(chunks, ["a\nb", "c"])

    def test_agent_results_are_visually_separated(self):
        text = append_agent_results(
            "HTTP: OK",
            [
                {
                    "agent_id": "Earth",
                    "country": "RU",
                    "region": "Saint-Petersburg",
                    "http": {
                        "ok": True,
                        "status_code": 200,
                        "method": "HEAD",
                        "latency_ms": 1117,
                        "url": "https://example.com",
                    },
                }
            ],
        )

        self.assertIn("🌍 Проверки агентами", text)
        self.assertIn("• Earth [RU, Saint-Petersburg]", text)
        self.assertIn("  HTTP: OK", text)

    def test_append_agent_results_replaces_existing_agent_block(self):
        base_text = append_agent_results(
            "HTTP: OK\nSSL: 71 дней до истечения",
            [
                {
                    "agent_id": "Earth",
                    "country": "RU",
                    "region": "Saint-Petersburg",
                    "http": {"ok": True, "status_code": 200, "method": "HEAD", "latency_ms": 115},
                }
            ],
        )

        text = append_agent_results(
            f"🔗 https://glut1.ru\n{base_text}\n🕒 Последняя проверка: 2026-07-03 11:19:36",
            [
                {
                    "agent_id": "Earth",
                    "country": "RU",
                    "region": "Saint-Petersburg",
                    "checked_at": datetime(2026, 7, 3, 11, 19, 36),
                    "http": {"ok": True, "status_code": 200, "method": "HEAD", "latency_ms": 115},
                }
            ],
        )

        self.assertEqual(text.count("🌍 Проверки агентами"), 1)
        self.assertEqual(text.count("• Earth [RU, Saint-Petersburg]"), 1)


if __name__ == "__main__":
    unittest.main()
