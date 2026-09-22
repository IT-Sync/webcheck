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

        self.assertIn("/app/static/app.css?v=3", source)
        self.assertIn("/app/static/app.js?v=3", source)


if __name__ == "__main__":
    unittest.main()
