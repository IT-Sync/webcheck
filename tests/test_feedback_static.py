import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATABASE = ROOT / "bot" / "infra" / "db.py"
SCHEMA = ROOT / "bot" / "infra" / "schema.py"
HANDLERS = ROOT / "bot" / "telegram" / "handlers.py"
WEBAPP = ROOT / "bot" / "webapp" / "server.py"


class FeedbackStaticTest(unittest.TestCase):
    def test_feedback_schema_preserves_conversations_and_messages(self):
        source = SCHEMA.read_text(encoding="utf-8")

        self.assertIn("CREATE TABLE IF NOT EXISTS feedback_conversations", source)
        self.assertIn("CREATE TABLE IF NOT EXISTS feedback_messages", source)
        self.assertIn("ON DELETE CASCADE", source)

    def test_feedback_schema_stores_telegram_media_without_binary_payloads(self):
        source = SCHEMA.read_text(encoding="utf-8") + DATABASE.read_text(encoding="utf-8")

        self.assertIn("telegram_file_id TEXT", source)
        self.assertIn("media_group_id TEXT", source)
        self.assertIn("active_media_group_id TEXT", source)
        self.assertNotIn("file_data BYTEA", source)

    def test_pending_feedback_is_handled_before_universal_site_input(self):
        source = HANDLERS.read_text(encoding="utf-8")

        self.assertIn("class FeedbackPendingFilter", source)
        self.assertLess(
            source.index("async def receive_feedback"),
            source.index("async def universal_add"),
        )
        self.assertIn("Failed to notify feedback owner", source)

    def test_feedback_accepts_captions_and_supported_attachments(self):
        source = HANDLERS.read_text(encoding="utf-8")

        self.assertIn("message.text or message.caption", source)
        self.assertIn("def feedback_attachment", source)
        self.assertIn("message.photo[-1]", source)
        self.assertIn("message.bot.copy_message", source)

    def test_webapp_feedback_start_is_authenticated_and_registered(self):
        source = WEBAPP.read_text(encoding="utf-8")

        handler_position = source.index("async def start_feedback")
        self.assertIn("@require_telegram_user", source[handler_position - 40:handler_position])
        self.assertIn('/api/webapp/feedback/start', source)


if __name__ == "__main__":
    unittest.main()
