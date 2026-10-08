import ast
import asyncio
import json
import logging
import re
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from aiohttp import web

from bot.checks import monitor as checks
from bot.checks.service import check_resource
from bot.core.target_validation import TargetValidationError, validate_monitoring_target
from bot.core.url_utils import is_valid_monitoring_url


ROOT = Path(__file__).resolve().parents[1]
INVALID_URLS = (None, "", "  ", 123, "https://None", "ftp://example.com", "https://example.com:bad")


def load_functions(path, names, namespace):
    """Execute actual functions against doubles without initializing the database."""
    tree = ast.parse((ROOT / path).read_text())
    functions = [node for node in tree.body
                 if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names]
    for function in functions:
        function.decorator_list = []
    exec(compile(ast.Module(body=functions, type_ignores=[]), path, "exec"), namespace)
    return namespace


class TargetShapeTest(unittest.TestCase):
    def test_invalid_shapes_are_rejected_without_coercion(self):
        for value in INVALID_URLS:
            with self.subTest(value=value):
                self.assertFalse(is_valid_monitoring_url(value))
        self.assertTrue(is_valid_monitoring_url("https://example.com"))
        self.assertTrue(is_valid_monitoring_url("http://example.com:8080/path"))

    def test_persistence_rejects_invalid_urls_before_any_database_work(self):
        cursor = Mock()
        connection = Mock()
        personal_project = Mock()
        namespace = load_functions('bot/infra/db.py', {'add_site', 'add_site_to_project'},
                                   dict(c=cursor, conn=connection, ensure_personal_project=personal_project,
                                        is_valid_monitoring_url=is_valid_monitoring_url))
        for value in INVALID_URLS:
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    namespace['add_site'](42, value)
                with self.assertRaises(ValueError):
                    namespace['add_site_to_project'](42, 1, value)
        cursor.execute.assert_not_called()
        connection.commit.assert_not_called()
        personal_project.assert_not_called()


class InvalidCheckTest(unittest.IsolatedAsyncioTestCase):
    async def test_successful_validation_returns_normalized_url(self):
        with patch('bot.core.target_validation.resolve_public_addresses', AsyncMock(return_value=['8.8.8.8'])) as dns:
            result = await validate_monitoring_target('Example.COM/path')
        self.assertEqual(result, 'https://example.com')
        dns.assert_awaited_once_with('https://example.com', dns_timeout_seconds=3)

    async def test_invalid_targets_do_not_open_network_clients_or_run_followup_checks(self):
        with patch.object(checks.aiohttp, 'ClientSession') as session, \
                patch('bot.checks.service.check_ssl', AsyncMock()) as ssl_check, \
                patch('bot.checks.service.check_domain_expiry', AsyncMock()) as domain_check, \
                patch('bot.core.target_validation.asyncio.to_thread', AsyncMock()) as lookup:
            for value in INVALID_URLS:
                with self.subTest(value=value):
                    result = await check_resource(value)
                    self.assertFalse(result.http['ok'])
                    self.assertTrue(result.http['target_validation_failed'])
                    self.assertEqual(result.http['attempts'], 0)
                    self.assertEqual(result.ssl_days, -1)
            session.assert_not_called()
            lookup.assert_not_awaited()
            ssl_check.assert_not_awaited()
            domain_check.assert_not_awaited()

    async def test_direct_ssl_and_domain_checks_reject_invalid_urls_before_io(self):
        with patch.object(checks.socket, 'create_connection') as connect, \
                patch.object(checks.asyncio, 'create_subprocess_exec', AsyncMock()) as whois:
            for value in INVALID_URLS:
                self.assertEqual(checks._check_ssl_sync(value), -1)
                self.assertEqual(await checks.check_domain_expiry(value), (-1, None, None))
            connect.assert_not_called()
            whois.assert_not_awaited()

    async def test_invalid_targets_are_not_sent_to_remote_agents(self):
        dispatch = AsyncMock()
        namespace = load_functions('bot/agent_server/checks.py', {'check_with_agents'},
                                   dict(AGENT_CHECKS_ENABLED=True,
                                        is_valid_monitoring_url=is_valid_monitoring_url,
                                        AGENT_REGISTRY=SimpleNamespace(request_check_all=dispatch)))
        for value in INVALID_URLS:
            self.assertEqual(await namespace['check_with_agents'](value), [])
        dispatch.assert_not_awaited()

    async def test_repeated_scheduler_runs_skip_invalid_rows_and_continue_other_sites(self):
        check = AsyncMock(side_effect=RuntimeError('test check reached'))
        bot = SimpleNamespace(send_message=AsyncMock())
        rows = [(1, 42, None), (2, 42, 'https://example.com', None, None, None, None, None, [], None, {})]
        namespace = load_functions('bot/telegram/scheduler.py',
                                   {'monitor', 'process_site_limited', 'process_site'},
                                   dict(asyncio=asyncio, logging=logging, MAX_CONCURRENT_CHECKS=2,
                                        get_all_site_checks=Mock(return_value=rows),
                                        is_valid_monitoring_url=is_valid_monitoring_url,
                                        check_resource=check, MONITOR_HTTP_RETRIES=1,
                                        MONITOR_HTTP_DELAY_SECONDS=0, MONITOR_HTTP_TIMEOUT_SECONDS=1,
                                        TelegramForbiddenError=type('TelegramForbiddenError', (Exception,), {})))
        with self.assertLogs(level='WARNING'):
            await namespace['monitor'](bot)
            await namespace['monitor'](bot)
        self.assertEqual(check.await_count, 2)
        self.assertTrue(all(call.args == ('https://example.com',) for call in check.await_args_list))
        self.assertTrue(all('None' not in call.args[1] for call in bot.send_message.await_args_list))

    async def test_manual_api_check_rejects_invalid_resource_before_network_work(self):
        check = AsyncMock()
        dispatch = AsyncMock()
        namespace = load_functions('bot/webapp/server.py', {'check_site', '_json_error'},
                                   dict(web=web, _owned_site=Mock(return_value=(7, 42, None, None)),
                                        get_site_role=Mock(return_value='owner'),
                                        is_valid_monitoring_url=is_valid_monitoring_url,
                                        check_resource=check, check_with_agents=dispatch))
        response = await namespace['check_site']({'telegram_user': SimpleNamespace(id=42)})
        self.assertEqual(response.status, 400)
        self.assertEqual(json.loads(response.text)['error']['code'], 'invalid_target')
        check.assert_not_awaited()
        dispatch.assert_not_awaited()

    async def test_manual_telegram_check_reports_invalid_resource_without_network(self):
        check = AsyncMock()
        dispatch = AsyncMock()
        bot = SimpleNamespace(send_message=AsyncMock())
        namespace = load_functions('bot/telegram/handlers.py', {'send_status_report'},
                                   dict(is_valid_monitoring_url=is_valid_monitoring_url,
                                        check_resource=check, check_with_agents=dispatch))
        await namespace['send_status_report'](42, None, bot, site_id=7)
        bot.send_message.assert_awaited_once()
        self.assertIn('Некорректный адрес', bot.send_message.await_args.args[1])
        check.assert_not_awaited()
        dispatch.assert_not_awaited()


class ResourceCreationTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.insert = Mock(return_value=7)
        self.namespace = load_functions('bot/webapp/server.py',
            {'create_site', 'bulk_sites', '_clean_group', '_clean_tags', '_json_error'},
            dict(web=web, re=re, WEB_APP_MAX_SITES_PER_USER=50, WEB_APP_DNS_TIMEOUT_SECONDS=3,
                 validate_monitoring_target=validate_monitoring_target,
                 TargetValidationError=TargetValidationError,
                 ensure_personal_project=Mock(return_value=1),
                 get_project_role=Mock(return_value='owner'), get_project_site_count=Mock(return_value=0),
                 get_site_by_url_in_project=Mock(return_value=None), add_site_to_project=self.insert,
                 set_site_tags_by_id=Mock(), log_user_action=Mock(),
                 _site_payload_for_user=Mock(return_value={'id': 7, 'url': 'https://example.com'})))

    def request(self, data):
        class Request(dict):
            json = AsyncMock(return_value=data)
        return Request(telegram_user=SimpleNamespace(id=42, username='user'))

    async def test_single_add_saves_actual_url_without_http_availability_check(self):
        with patch('bot.core.target_validation.resolve_public_addresses', AsyncMock(return_value=['8.8.8.8'])):
            response = await self.namespace['create_site'](self.request({'url': 'Example.COM', 'project_id': 1}))
        self.assertEqual(response.status, 201)
        self.insert.assert_called_once_with(42, 1, 'https://example.com', 'user', '')

    async def test_bulk_add_saves_urls_and_preserves_partial_failure_results(self):
        with patch('bot.core.target_validation.resolve_public_addresses', AsyncMock(return_value=['8.8.8.8'])):
            response = await self.namespace['bulk_sites'](self.request({
                'action': 'add', 'project_id': 1, 'urls': ['Example.COM', None, 'second.example'],
            }))
        results = json.loads(response.text)['results']
        self.assertEqual([result['ok'] for result in results], [True, False, True])
        self.assertEqual([call.args[2] for call in self.insert.call_args_list],
                         ['https://example.com', 'https://second.example'])
