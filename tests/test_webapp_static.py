import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "bot" / "webapp" / "static" / "index.html"
SCRIPT = ROOT / "bot" / "webapp" / "static" / "app.js"


class WebAppStaticMarkupTest(unittest.TestCase):
    def test_dialog_close_button_bypasses_required_field_validation(self):
        source = INDEX.read_text(encoding="utf-8")

        self.assertIn('id="close-add"', source)
        self.assertIn('value="cancel"', source)
        self.assertIn('type="submit"', source)
        self.assertIn("formnovalidate", source)

    def test_frontend_assets_have_cache_busting_version(self):
        source = INDEX.read_text(encoding="utf-8")

        self.assertIn("/app/static/app.css?v=6", source)
        self.assertIn("/app/static/app.js?v=6", source)

    def test_status_metrics_are_filter_controls(self):
        source = INDEX.read_text(encoding="utf-8")

        self.assertIn('data-filter="attention"', source)
        self.assertIn('id="sort-select"', source)
        self.assertIn('value="priority"', source)

    def test_direct_access_uses_a_separate_placeholder(self):
        markup = INDEX.read_text(encoding="utf-8")
        script = SCRIPT.read_text(encoding="utf-8")

        self.assertIn('id="access-gate"', markup)
        self.assertIn('id="app-shell" hidden', markup)
        self.assertIn("if (!telegram?.initData)", script)
        self.assertIn("accessGate.hidden = false", script)
        self.assertLess(
            script.index("if (!telegram?.initData)"),
            script.index('fetch(path'),
        )


if __name__ == "__main__":
    unittest.main()
