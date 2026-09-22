import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "bot" / "webapp" / "static" / "index.html"


class WebAppStaticMarkupTest(unittest.TestCase):
    def test_dialog_close_button_bypasses_required_field_validation(self):
        source = INDEX.read_text(encoding="utf-8")

        self.assertIn('id="close-add"', source)
        self.assertIn('value="cancel"', source)
        self.assertIn('type="submit"', source)
        self.assertIn("formnovalidate", source)

    def test_frontend_assets_have_cache_busting_version(self):
        source = INDEX.read_text(encoding="utf-8")

        self.assertIn("/app/static/app.css?v=4", source)
        self.assertIn("/app/static/app.js?v=4", source)

    def test_status_metrics_are_filter_controls(self):
        source = INDEX.read_text(encoding="utf-8")

        self.assertIn('data-filter="attention"', source)
        self.assertIn('id="sort-select"', source)
        self.assertIn('value="priority"', source)


if __name__ == "__main__":
    unittest.main()
