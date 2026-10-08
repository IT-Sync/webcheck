import ast
import os
import re
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from aiohttp import web

from bot.admin_console.layout import esc, page
from bot.core.confirmation import ConfirmationStore
from bot.telegram import deletion
import bot.infra


ROOT = Path(__file__).resolve().parents[1]


class ConfirmationStoreTest(unittest.TestCase):
    def test_confirmation_is_bound_to_actor_action_target_and_single_use(self):
        store = ConfirmationStore()
        token = store.issue("site", 1, "actor")
        self.assertIsNone(store.take(token, "other"))
        self.assertIsNone(store.take(token, "actor", action="user"))
        self.assertIsNone(store.take(token, "actor", target_id=2))
        self.assertEqual(store.take(token, "actor", action="site", target_id=1).target_id, 1)
        self.assertIsNone(store.take(token, "actor"))

    def test_expired_confirmation_is_rejected(self):
        store = ConfirmationStore()
        with patch("bot.core.confirmation.time.monotonic", return_value=100):
            token = store.issue("site", 1, "actor")
        with patch("bot.core.confirmation.time.monotonic", return_value=400):
            self.assertIsNone(store.take(token, "actor"))

    def test_pending_storage_is_bounded(self):
        store = ConfirmationStore(max_pending=2)
        oldest = store.issue("site", 1, "actor")
        store.issue("site", 2, "actor")
        store.issue("site", 3, "actor")
        self.assertEqual(len(store.pending), 2)
        self.assertIsNone(store.take(oldest, "actor"))


class AdminDeletionTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        # Execute real handlers with substituted persistence, avoiding DB startup.
        tree = ast.parse((ROOT / "bot/admin_console/server.py").read_text())
        names = {"is_authenticated", "require_auth", "deletion_confirmation",
                 "deletion_is_confirmed", "delete_user", "delete_site"}
        functions = [item for item in tree.body
                     if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name in names]
        self.store = ConfirmationStore()
        self.delete_user = Mock(return_value=(2, 3, 4))
        self.delete_site = Mock(return_value=True)
        namespace = dict(web=web, page=page, esc=esc, ADMIN_WEB_TOKEN="test-token",
                         BOT_OWNER_ID=42, _delete_confirmations=self.store,
                         get_admin_user=Mock(return_value={"username": '<script>alert(1)</script>', "site_count": 2}),
                         get_site_by_id=Mock(return_value=(7, 123, None, 'https://example.com/<script>')),
                         delete_user_data=self.delete_user, admin_delete_site_by_id=self.delete_site,
                         log_user_action=Mock())
        exec(compile(ast.Module(body=functions, type_ignores=[]), "server.py", "exec"), namespace)
        self.handlers = namespace

    async def post(self, path, data=None, authenticated=True):
        parts = path.split('/')
        kind, target = parts[2:4]
        key = 'user_id' if kind == 'users' else 'site_id'
        request = SimpleNamespace(
            match_info={key: target}, cookies={'admin_token': 'test-token'} if authenticated else {},
            query={}, post=AsyncMock(return_value=data or {}),
        )
        try:
            return await self.handlers['delete_user' if kind == 'users' else 'delete_site'](request)
        except web.HTTPException as response:
            return response

    async def prompt(self, kind, target_id):
        response = await self.post(f'/admin/{kind}/{target_id}/delete')
        self.assertEqual(response.status, 200)
        body = response.text
        self.delete_user.assert_not_called()
        self.delete_site.assert_not_called()
        self.assertIn("Отмена", body)
        self.assertIn("&lt;script&gt;", body)
        self.assertEqual(response.headers['Cache-Control'], 'no-store')
        return re.search(r'name="confirmation" value="([^"]+)"', body).group(1)

    async def test_initial_user_and_site_posts_only_show_confirmation(self):
        await self.prompt('users', 123)
        await self.prompt('sites', 7)

    async def test_confirmed_user_deletion_is_single_use(self):
        token = await self.prompt('users', 123)
        data = dict(confirmation=token, confirm_target='123')
        response = await self.post('/admin/users/123/delete', data)
        self.assertEqual(response.status, 302)
        self.delete_user.assert_called_once_with(123)
        response = await self.post('/admin/users/123/delete', data)
        self.assertEqual(response.status, 400)
        self.delete_user.assert_called_once()

    async def test_confirmed_site_deletion_only_deletes_selected_site(self):
        token = await self.prompt('sites', 7)
        response = await self.post('/admin/sites/7/delete', dict(confirmation=token, confirm_target='7'))
        self.assertEqual(response.status, 302)
        self.delete_site.assert_called_once_with(7)
        self.delete_user.assert_not_called()

    async def test_forged_wrong_target_and_missing_explicit_confirmation_do_not_delete(self):
        token = await self.prompt('users', 123)
        for path, data in (
            ('/admin/users/123/delete', dict(confirmation='forged', confirm_target='123')),
            ('/admin/users/123/delete', dict(confirmation=token)),
            ('/admin/users/124/delete', dict(confirmation=token, confirm_target='124')),
            ('/admin/sites/123/delete', dict(confirmation=token, confirm_target='123')),
        ):
            response = await self.post(path, data)
            self.assertEqual(response.status, 400)
        self.delete_user.assert_not_called()
        self.delete_site.assert_not_called()

    async def test_expired_confirmation_does_not_delete(self):
        token = await self.prompt('users', 123)
        pending = self.store.pending[token]
        from dataclasses import replace
        self.store.pending[token] = replace(pending, expires_at=0)
        response = await self.post('/admin/users/123/delete', dict(confirmation=token, confirm_target='123'))
        self.assertEqual(response.status, 400)
        self.delete_user.assert_not_called()

    async def test_authentication_is_still_required_for_confirmed_post(self):
        token = await self.prompt('users', 123)
        response = await self.post('/admin/users/123/delete',
                                   dict(confirmation=token, confirm_target='123'), authenticated=False)
        self.assertEqual(response.status, 302)
        self.assertEqual(response.headers['Location'], '/admin/login')
        self.delete_user.assert_not_called()

    async def test_shared_project_guard_is_preserved(self):
        token = await self.prompt('users', 123)
        self.delete_user.side_effect = ValueError('owned_projects_have_members')
        response = await self.post('/admin/users/123/delete', dict(confirmation=token, confirm_target='123'))
        self.assertEqual(response.status, 409)


class TelegramDeletionTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        deletion._confirmations = ConfirmationStore()
        async def run_in_thread(function, *args):
            return function(*args)
        self.thread_patch = patch('bot.telegram.deletion.asyncio.to_thread', side_effect=run_in_thread)
        self.thread_patch.start()
        self.addCleanup(self.thread_patch.stop)
        self.db = SimpleNamespace(
            get_admin_user=Mock(return_value={'site_count': 2}),
            get_site_by_id=Mock(return_value=(7, 123, None, 'https://example.com/<script>')),
            get_site_for_user=Mock(return_value=(7, 123, None, 'https://example.com/<script>')),
            get_site_role=Mock(return_value='owner'),
            delete_user_data=Mock(return_value=(2, 3, 4)),
            admin_delete_site_by_id=Mock(return_value=True),
            delete_site_by_id=Mock(return_value=True), log_user_action=Mock(),
        )
        self.patch_db = patch.object(bot.infra, 'db', self.db, create=True)
        self.patch_db.start()
        self.addCleanup(self.patch_db.stop)
        self.patch_env = patch.dict(os.environ, {'BOT_OWNER_ID': '42'})
        self.patch_env.start()
        self.addCleanup(self.patch_env.stop)
        self.message = SimpleNamespace(chat=SimpleNamespace(id=100), answer=AsyncMock(), edit_text=AsyncMock())

    def callback(self, data, user_id=42, chat_id=100):
        message = SimpleNamespace(chat=SimpleNamespace(id=chat_id), edit_text=AsyncMock())
        return SimpleNamespace(data=data, from_user=SimpleNamespace(id=user_id, username='user'),
                               message=message, answer=AsyncMock())

    def button_data(self, index=0):
        keyboard = self.message.answer.await_args.kwargs['reply_markup']
        data = keyboard.inline_keyboard[0][index].callback_data
        self.assertLessEqual(len(data.encode()), 64)
        return data

    async def test_user_prompt_cancel_and_stale_button_never_delete(self):
        await deletion.prompt_user_deletion(self.message, 42, 123)
        self.db.delete_user_data.assert_not_called()
        confirm = self.button_data()
        await deletion.handle_deletion_confirmation(self.callback(self.button_data(1)))
        await deletion.handle_deletion_confirmation(self.callback(confirm))
        self.db.delete_user_data.assert_not_called()

    async def test_confirmation_cannot_be_used_by_another_user_or_chat(self):
        await deletion.prompt_user_deletion(self.message, 42, 123)
        data = self.button_data()
        await deletion.handle_deletion_confirmation(self.callback(data, user_id=43))
        await deletion.handle_deletion_confirmation(self.callback(data, chat_id=101))
        self.db.delete_user_data.assert_not_called()
        await deletion.handle_deletion_confirmation(self.callback(data))
        await deletion.handle_deletion_confirmation(self.callback(data))
        self.db.delete_user_data.assert_called_once_with(123)

    async def test_site_confirm_rechecks_permissions_and_uses_id(self):
        await deletion.prompt_site_deletion(self.message, 123, 7)
        self.db.delete_site_by_id.assert_not_called()
        self.assertNotIn('<script>', self.message.answer.await_args.args[0])
        await deletion.handle_deletion_confirmation(self.callback(self.button_data(), user_id=123))
        self.db.delete_site_by_id.assert_called_once_with(7, 123)
        self.db.delete_user_data.assert_not_called()

    async def test_changed_membership_prevents_deletion(self):
        await deletion.prompt_site_deletion(self.message, 123, 7)
        self.db.get_site_role.return_value = 'viewer'
        await deletion.handle_deletion_confirmation(self.callback(self.button_data(), user_id=123))
        self.db.delete_site_by_id.assert_not_called()

    async def test_admin_site_deletion_requires_confirmation_and_owner(self):
        await deletion.prompt_site_deletion(self.message, 42, 7, admin=True)
        self.db.admin_delete_site_by_id.assert_not_called()
        await deletion.handle_deletion_confirmation(self.callback(self.button_data()))
        self.db.admin_delete_site_by_id.assert_called_once_with(7)

    async def test_viewer_and_non_owner_cannot_request_privileged_deletion(self):
        self.db.get_site_role.return_value = 'viewer'
        await deletion.prompt_site_deletion(self.message, 123, 7)
        self.assertNotIn('reply_markup', self.message.answer.await_args.kwargs)
        await deletion.prompt_user_deletion(self.message, 123, 123)
        self.assertNotIn('reply_markup', self.message.answer.await_args.kwargs)
        self.db.delete_user_data.assert_not_called()
