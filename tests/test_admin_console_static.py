import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "bot" / "admin_console" / "server.py"


class AdminConsoleStaticTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = SERVER.read_text(encoding="utf-8")

    def test_site_registry_has_a_dedicated_route_and_navigation_item(self):
        self.assertIn('(\"sites\", \"/admin/sites\", \"Сайты\")', self.source)
        self.assertIn('app.router.add_get(\"/admin/sites\", sites)', self.source)

    def test_site_registry_can_search_and_filter_all_rows(self):
        self.assertIn('id=\"site-registry-search\"', self.source)
        self.assertIn('id=\"site-registry-status\"', self.source)
        self.assertIn('data-site-row', self.source)
        self.assertIn('filterSiteRegistry', self.source)

    def test_site_registry_links_resources_to_their_owner(self):
        self.assertIn('/admin/users/{site[\'user_id\']}', self.source)
        self.assertIn('/admin/messages?user_id={site[\'user_id\']}', self.source)

    def test_feedback_inbox_and_reply_routes_are_registered(self):
        self.assertIn('(\"feedback\", \"/admin/feedback\", \"Обратная связь\")', self.source)
        self.assertIn('app.router.add_get(\"/admin/feedback\", feedback)', self.source)
        self.assertIn('/admin/feedback/{conversation_id:\\\\d+}/reply', self.source)

    def test_feedback_text_is_escaped_before_rendering(self):
        self.assertIn('esc(item["message_text"])', self.source)
        self.assertIn('Ответить от имени бота', self.source)

    def test_feedback_media_uses_an_authenticated_proxy(self):
        self.assertIn("async def feedback_media", self.source)
        self.assertIn('/admin/feedback/media/{message_id:\\\\d+}', self.source)
        self.assertIn('X-Content-Type-Options', self.source)
        self.assertIn('feedback_attachment_html(item)', self.source)

    def test_admin_tables_support_accessible_column_sorting(self):
        self.assertIn("function initializeSortableTables()", self.source)
        self.assertIn("header.setAttribute('aria-sort', 'none')", self.source)
        self.assertIn("event.key !== 'Enter' && event.key !== ' '", self.source)
        self.assertIn("new Intl.Collator('ru'", self.source)
        self.assertIn("initializeSortableTables();", self.source)


if __name__ == "__main__":
    unittest.main()
