import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bot"))

from callback_data import (
    admin_delete_callback,
    site_delete_callback,
    site_pause_callback,
    site_resume_callback,
    site_status_callback,
)
from url_utils import normalize_url


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


if __name__ == "__main__":
    unittest.main()
