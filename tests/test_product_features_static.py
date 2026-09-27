import importlib
import sys
import types
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "bot" / "infra" / "schema.py"
DB = ROOT / "bot" / "infra" / "db.py"
SERVER = ROOT / "bot" / "webapp" / "server.py"


class ProductFeatureStaticTest(unittest.TestCase):
    def test_additive_schema_contains_feature_storage(self):
        schema = SCHEMA.read_text(encoding="utf-8")
        migration = DB.read_text(encoding="utf-8")
        for table in ("site_check_settings", "site_dns_snapshots", "dns_change_events"):
            self.assertIn(f"CREATE TABLE IF NOT EXISTS {table}", schema)
        for table in ("notification_preferences", "status_pages",
                      "status_page_sites", "status_page_updates"):
            self.assertIn(f"CREATE TABLE IF NOT EXISTS {table}", schema)
        self.assertIn("acknowledged_by BIGINT", schema)
        self.assertIn("ADD COLUMN IF NOT EXISTS acknowledged_at", migration)

    def test_bulk_and_status_routes_are_bounded_and_authorized(self):
        source = SERVER.read_text(encoding="utf-8")
        self.assertIn("1 <= len(urls) <= 50", source)
        self.assertIn("1 <= len(site_ids) <= 100", source)
        self.assertIn('get_project_role(project_id, user.id) not in ("owner", "manager")', source)
        self.assertIn('get_project_role(project_id, user.id) != "owner"', source)
        self.assertIn("results.append", source)
        self.assertIn('/sites/{site_id:\\\\d+}/checks', source)
        self.assertIn("validate_monitoring_target", source)

    def test_public_renderer_escapes_copy_and_ignores_private_fields(self):
        fake_db = types.ModuleType("bot.infra.db")
        fake_db.get_public_status_page = lambda slug: None
        sys.modules.pop("bot.public_status.server", None)
        with patch.dict(sys.modules, {"bot.infra.db": fake_db}):
            renderer = importlib.import_module("bot.public_status.server")
        self.addCleanup(sys.modules.pop, "bot.public_status.server", None)
        page = {
            "name": "<Status>", "description": "<script>alert(1)</script>",
            "updated_at": datetime(2026, 9, 26, 12, 0),
            "services": [{"name": "API <primary>", "status": "operational",
                          "last_checked": datetime(2026, 9, 26, 11, 59),
                          "url": "https://private.example"}],
            "updates": [{"message": "Investigating <edge>",
                         "created_at": datetime(2026, 9, 26, 11, 58)}],
            "private_diagnostic": "secret-stack-trace",
        }
        html = renderer.render_status_page(page)
        self.assertIn("&lt;script&gt;", html)
        self.assertIn("API &lt;primary&gt;", html)
        self.assertNotIn("private.example", html)
        self.assertNotIn("secret-stack-trace", html)


if __name__ == "__main__":
    unittest.main()
