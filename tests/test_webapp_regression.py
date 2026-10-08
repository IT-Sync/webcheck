import ast
import shutil
import subprocess
import unittest
from datetime import datetime
from pathlib import Path

from bot.core.url_utils import is_valid_monitoring_url


ROOT = Path(__file__).resolve().parents[1]


class WebAppRegressionTest(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "Node.js is needed for frontend runtime regression checks")
    def test_add_bulk_cache_sort_filter_and_delete_with_null_values(self):
        result = subprocess.run(
            [shutil.which("node"), str(ROOT / "tests/webapp_regression.js"),
             str(ROOT / "bot/webapp/static/app.js")],
            capture_output=True, text=True, timeout=15,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_site_payload_does_not_emit_null_tags_or_url(self):
        # Load pure serializers without initializing the PostgreSQL module.
        tree = ast.parse((ROOT / "bot/webapp/server.py").read_text())
        functions = [item for item in tree.body if isinstance(item, ast.FunctionDef)
                     and item.name in ("_iso", "_status_kind", "_site_payload")]
        namespace = {"datetime": datetime, "is_valid_monitoring_url": is_valid_monitoring_url}
        exec(compile(ast.Module(body=functions, type_ignores=[]), "server.py", "exec"), namespace)
        row = (1, 42, None, None, None, None, False, "", False,
               None, None, None, [None, "api", "", 123, " "])
        payload = namespace["_site_payload"](row)
        self.assertEqual(payload["tags"], ["api"])
        self.assertEqual(payload["url"], "")
        self.assertEqual(payload["status_kind"], "warning")
        self.assertIn("Некорректный адрес", payload["last_status"])
        down = list(row)
        down[3] = "https://down.example"
        down[4] = "HTTP: DOWN"
        down[12] = None
        payload = namespace["_site_payload"](down)
        self.assertEqual(payload["status_kind"], "down")
        self.assertEqual(payload["tags"], [])
