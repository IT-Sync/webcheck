import ast
import asyncio
import json
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from aiohttp import web

from bot.core.content_checks import normalize_check_settings

ROOT = Path(__file__).resolve().parents[1]


def functions(path, names, namespace):
    tree = ast.parse((ROOT / path).read_text())
    nodes = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
             and node.name in names]
    for node in nodes:
        node.decorator_list = []
    exec(compile(ast.Module(nodes, type_ignores=[]), path, 'exec'), namespace)
    return namespace


class DnsMonitoringSettingsTest(unittest.TestCase):
    def test_defaults_preserve_monitoring_and_values_must_be_boolean(self):
        self.assertTrue(normalize_check_settings({})['dns_monitoring_enabled'])
        self.assertFalse(normalize_check_settings({'dns_monitoring_enabled': False})['dns_monitoring_enabled'])
        for value in (None, 'false', 0, 1, []):
            with self.subTest(value=value), self.assertRaises(ValueError):
                normalize_check_settings({'dns_monitoring_enabled': value})

    def setUp(self):
        self.cursor = Mock()
        self.conn = Mock()
        self.namespace = functions('bot/infra/db.py',
            {'get_site_check_settings', 'set_site_check_settings', 'record_dns_snapshot', 'get_pending_dns_changes'},
            dict(c=self.cursor, conn=self.conn, datetime=datetime, json=json, Json=lambda value: value,
                 _lock_managed_site=Mock(return_value=True)))

    def queries(self):
        return [call.args[0] for call in self.cursor.execute.call_args_list]

    def test_missing_settings_enable_dns_and_existing_settings_read_false(self):
        self.cursor.fetchone.return_value = None
        self.assertTrue(self.namespace['get_site_check_settings'](7)['dns_monitoring_enabled'])
        self.cursor.fetchone.return_value = ([], None, {}, False)
        self.assertFalse(self.namespace['get_site_check_settings'](7)['dns_monitoring_enabled'])

    def test_disable_preserves_history_resets_baseline_and_suppresses_pending_delivery(self):
        self.assertTrue(self.namespace['set_site_check_settings'](
            7, 42, normalize_check_settings({'dns_monitoring_enabled': False})))
        self.assertIn('baseline_required = TRUE', self.queries()[1])
        self.assertIn('UPDATE dns_change_events SET notified_at', self.queries()[2])
        self.assertFalse(any('DELETE' in query for query in self.queries()))
        self.conn.commit.assert_called_once()

    def test_legacy_persistence_caller_keeps_existing_disabled_setting(self):
        self.cursor.fetchone.return_value = ([], None, {}, False)
        self.namespace['set_site_check_settings'](7, 42, {
            'expected_status_codes': [204], 'required_text': None, 'json_assertions': {},
        })
        insert = next(call for call in self.cursor.execute.call_args_list
                      if 'INSERT INTO site_check_settings' in call.args[0])
        self.assertIs(insert.args[1][4], False)

    def test_failed_settings_update_rolls_back(self):
        self.cursor.execute.side_effect = RuntimeError('write failed')
        with self.assertRaises(RuntimeError):
            self.namespace['set_site_check_settings'](7, 42, normalize_check_settings({}))
        self.conn.rollback.assert_called_once()
        self.conn.commit.assert_not_called()

    def test_stale_inflight_snapshot_does_not_write_when_monitoring_is_disabled(self):
        self.cursor.fetchone.return_value = (False,)
        self.assertEqual(self.namespace['record_dns_snapshot'](7, 'https://example.com', {}), [])
        self.assertEqual(self.cursor.execute.call_count, 1)
        self.assertIn('FOR UPDATE OF site', self.queries()[0])
        self.conn.commit.assert_not_called()

    def test_reenabled_monitoring_refreshes_baseline_without_retrospective_events(self):
        self.cursor.fetchone.side_effect = [(True,), (['8.8.8.8'], ['ns.old'], ['10 mx.old'], True)]
        changes = self.namespace['record_dns_snapshot'](7, 'https://example.com', {
            'ips': ['1.1.1.1'], 'ns': ['ns.new'], 'mx': ['10 mx.new'],
        })
        self.assertEqual(changes, [])
        self.assertFalse(any('INSERT INTO dns_change_events' in query or 'INSERT INTO events' in query
                             for query in self.queries()))
        update = next(call for call in self.cursor.execute.call_args_list
                      if 'UPDATE site_dns_snapshots' in call.args[0])
        self.assertEqual(update.args[1][:3], (['1.1.1.1'], ['ns.new'], ['10 mx.new']))
        self.assertFalse(update.args[1][4])

    def test_partial_reenabled_snapshot_keeps_baseline_pending(self):
        self.cursor.fetchone.side_effect = [(True,), (['8.8.8.8'], ['ns.old'], ['10 mx.old'], True)]
        self.namespace['record_dns_snapshot'](7, 'https://example.com', {
            'ips': ['1.1.1.1'], 'ns': None, 'mx': ['10 mx.new'],
        })
        update = next(call for call in self.cursor.execute.call_args_list
                      if 'UPDATE site_dns_snapshots' in call.args[0])
        self.assertEqual(update.args[1][1], ['ns.old'])
        self.assertTrue(update.args[1][4])

    def test_enabled_monitoring_still_records_new_changes(self):
        self.cursor.fetchone.side_effect = [(True,), (['8.8.8.8'], ['ns.old'], ['10 mx.old'], False), (9,)]
        changes = self.namespace['record_dns_snapshot'](7, 'https://example.com', {
            'ips': ['1.1.1.1'], 'ns': ['ns.old'], 'mx': ['10 mx.old'],
        })
        self.assertEqual([change['record_type'] for change in changes], ['IP'])
        self.assertTrue(any('INSERT INTO events' in query for query in self.queries()))

    def test_pending_delivery_query_respects_current_monitoring_setting(self):
        self.cursor.fetchall.return_value = []
        self.namespace['get_pending_dns_changes'](7)
        query, params = self.cursor.execute.call_args.args
        self.assertIn('dns_monitoring_enabled', query)
        self.assertEqual(params, (7, 7))

    def test_upgrade_is_additive_and_defaults_are_compatible(self):
        source = (ROOT / 'bot/infra/db.py').read_text()
        self.assertIn('ADD COLUMN IF NOT EXISTS dns_monitoring_enabled BOOLEAN NOT NULL DEFAULT TRUE', source)
        self.assertIn('ADD COLUMN IF NOT EXISTS baseline_required BOOLEAN NOT NULL DEFAULT FALSE', source)


class DnsMonitoringFlowTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.resolve = AsyncMock(return_value={'ips': ['8.8.8.8'], 'ns': [], 'mx': []})
        self.record = Mock()
        self.pending = Mock(return_value=[{'id': 9}])
        self.mark = Mock()
        self.bot = SimpleNamespace(send_message=AsyncMock())
        async def thread_call(function, *args, **kwargs):
            return function(*args, **kwargs)
        self.namespace = functions('bot/telegram/scheduler.py', {'monitor_site_dns'},
            dict(asyncio=SimpleNamespace(to_thread=thread_call), resolve_dns_snapshot=self.resolve,
                 record_dns_snapshot=self.record, get_pending_dns_changes=self.pending,
                 mark_dns_changes_notified=self.mark, format_dns_change_alert=Mock(return_value='DNS alert'),
                 TelegramForbiddenError=type('TelegramForbiddenError', (Exception,), {})))

    async def run_dns(self, **kwargs):
        return await self.namespace['monitor_site_dns'](
            self.bot, 7, 42, 'https://example.com', {'ip': '8.8.8.8'},
            {'notify_dns': kwargs.pop('notify_dns', True)}, datetime.utcnow(), **kwargs,
        )

    async def test_disabled_monitoring_skips_dns_work_events_and_alerts(self):
        self.assertTrue(await self.run_dns(enabled=False))
        self.resolve.assert_not_awaited()
        self.record.assert_not_called()
        self.pending.assert_not_called()
        self.bot.send_message.assert_not_awaited()

    async def test_default_enabled_monitoring_still_records_and_notifies(self):
        self.assertTrue(await self.run_dns())
        self.resolve.assert_awaited_once()
        self.record.assert_called_once()
        self.bot.send_message.assert_awaited_once()
        self.mark.assert_called_once()

    async def test_disabling_only_notifications_keeps_monitoring_events(self):
        self.assertTrue(await self.run_dns(notify_dns=False))
        self.record.assert_called_once()
        self.bot.send_message.assert_not_awaited()
        self.mark.assert_called_once()

    async def test_older_api_requests_preserve_disabled_dns_and_other_settings(self):
        saved = Mock(return_value=True)
        namespace = functions('bot/webapp/server.py', {'site_check_settings', '_json_error'},
            dict(web=web, normalize_check_settings=normalize_check_settings,
                 _owned_site=Mock(return_value=(7, 42, None, 'https://example.com')),
                 get_site_role=Mock(return_value='owner'),
                 get_site_check_settings=Mock(return_value=normalize_check_settings({
                     'dns_monitoring_enabled': False, 'required_text': 'healthy',
                 })), set_site_check_settings=saved,
                 validate_monitoring_target=AsyncMock(), WEB_APP_DNS_TIMEOUT_SECONDS=3,
                 TargetValidationError=ValueError, log_user_action=Mock()))
        class Request(dict):
            method = 'PUT'
            json = AsyncMock(return_value={'expected_status_codes': [204]})
        response = await namespace['site_check_settings'](Request(telegram_user=SimpleNamespace(id=42, username='user')))
        self.assertEqual(response.status, 200)
        settings = saved.call_args.args[2]
        self.assertFalse(settings['dns_monitoring_enabled'])
        self.assertEqual(settings['required_text'], 'healthy')
        self.assertEqual(settings['expected_status_codes'], [204])
