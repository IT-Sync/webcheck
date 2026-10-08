import os
import unittest
from unittest.mock import AsyncMock, patch

from bot.telegram.commands import PUBLIC_COMMANDS, OWNER_COMMANDS, configure_bot_commands


class TelegramCommandsTest(unittest.IsolatedAsyncioTestCase):
    async def test_public_and_owner_menus_use_separate_scopes_and_languages(self):
        bot = AsyncMock()
        with patch.dict(os.environ, {"BOT_OWNER_ID": "42"}):
            await configure_bot_commands(bot)

        self.assertEqual(bot.set_my_commands.await_count, 6)
        for call in bot.set_my_commands.await_args_list:
            names = {command.command for command in call.args[0]}
            self.assertTrue({name for name, _ in PUBLIC_COMMANDS} <= names)
            self.assertIn(call.kwargs["language_code"], ("", "ru"))
            scope = call.kwargs["scope"]
            if scope.type == "chat":
                self.assertEqual(scope.chat_id, 42)
                self.assertTrue({name for name, _ in OWNER_COMMANDS} <= names)
            else:
                self.assertFalse({name for name, _ in OWNER_COMMANDS} & names)

    async def test_no_owner_does_not_register_a_chat_scope(self):
        bot = AsyncMock()
        with patch.dict(os.environ, {"BOT_OWNER_ID": "0"}):
            await configure_bot_commands(bot)
        self.assertEqual(bot.set_my_commands.await_count, 4)

    async def test_menu_failure_does_not_abort_startup_or_other_scopes(self):
        bot = AsyncMock()
        bot.set_my_commands.side_effect = [RuntimeError("offline"), None, None, None]
        with patch.dict(os.environ, {"BOT_OWNER_ID": "0"}), self.assertLogs(
            "bot.telegram.commands", level="ERROR",
        ):
            await configure_bot_commands(bot)
        self.assertEqual(bot.set_my_commands.await_count, 4)
