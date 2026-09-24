import importlib
import os
import sys
import threading
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch
from uuid import uuid4

from psycopg2.extensions import parse_dsn

from bot.infra.maintenance import _archive_hourly_batch
from bot.infra.repository import DatabaseRepository


@unittest.skipUnless(
    os.getenv("TEST_DATABASE_URL"),
    "set TEST_DATABASE_URL to run PostgreSQL integration tests",
)
class PostgreSQLRepositoryIntegrationTest(unittest.TestCase):
    def setUp(self):
        self.repository = DatabaseRepository(
            dsn=os.environ["TEST_DATABASE_URL"],
            min_connections=1,
            max_connections=3,
        )
        self.schema = f"repository_test_{uuid4().hex}"
        with self.repository.transaction() as cursor:
            cursor.execute(f'CREATE SCHEMA "{self.schema}"')
            cursor.execute(
                f'CREATE TABLE "{self.schema}".items '
                "(id SERIAL PRIMARY KEY, value INTEGER NOT NULL)"
            )

    def tearDown(self):
        try:
            with self.repository.transaction() as cursor:
                cursor.execute(f'DROP SCHEMA IF EXISTS "{self.schema}" CASCADE')
        finally:
            self.repository.close()

    def test_rolls_hourly_rows_into_daily_storage(self):
        url = f"https://rollup-{uuid4().hex}.example"
        now = datetime.utcnow().replace(minute=0, second=0, microsecond=0)
        with self.repository.transaction() as cursor:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS agent_check_hourly (
                    bucket_start TIMESTAMP NOT NULL,
                    url TEXT NOT NULL,
                    agent_id TEXT NOT NULL,
                    country TEXT,
                    region TEXT,
                    checks INTEGER NOT NULL DEFAULT 0,
                    successful_checks INTEGER NOT NULL DEFAULT 0,
                    latency_sum_ms BIGINT NOT NULL DEFAULT 0,
                    latency_samples INTEGER NOT NULL DEFAULT 0,
                    max_latency_ms INTEGER,
                    PRIMARY KEY (bucket_start, url, agent_id)
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS agent_check_daily (
                    LIKE agent_check_hourly INCLUDING ALL
                )
                """
            )
            cursor.execute(
                """
                INSERT INTO agent_check_hourly (
                    bucket_start, url, agent_id, country, region, checks,
                    successful_checks, latency_sum_ms, latency_samples,
                    max_latency_ms
                )
                VALUES
                    (%s, %s, 'agent-1', 'RU', 'Moscow', 3, 2, 300, 3, 150),
                    (%s, %s, 'agent-1', 'RU', 'Moscow', 2, 2, 180, 2, 100)
                """,
                (now - timedelta(hours=2), url, now - timedelta(hours=1), url),
            )
            self.assertEqual(_archive_hourly_batch(cursor, now, 100), 2)

        with self.repository.transaction() as cursor:
            cursor.execute(
                """
                SELECT checks, successful_checks, latency_sum_ms,
                       latency_samples, max_latency_ms
                FROM agent_check_daily
                WHERE url = %s
                """,
                (url,),
            )
            self.assertEqual(cursor.fetchone(), (5, 4, 480, 5, 150))
            cursor.execute(
                "SELECT COUNT(*) FROM agent_check_hourly WHERE url = %s",
                (url,),
            )
            self.assertEqual(cursor.fetchone()[0], 0)
            cursor.execute("DELETE FROM agent_check_daily WHERE url = %s", (url,))

    def test_transaction_commits_and_rolls_back(self):
        with self.repository.transaction() as cursor:
            cursor.execute(
                f'INSERT INTO "{self.schema}".items (value) VALUES (%s)',
                (1,),
            )

        with self.assertRaisesRegex(RuntimeError, "rollback"):
            with self.repository.transaction() as cursor:
                cursor.execute(
                    f'INSERT INTO "{self.schema}".items (value) VALUES (%s)',
                    (2,),
                )
                raise RuntimeError("rollback")

        with self.repository.transaction() as cursor:
            cursor.execute(f'SELECT value FROM "{self.schema}".items ORDER BY id')
            self.assertEqual(cursor.fetchall(), [(1,)])

    def test_compatibility_facade_preserves_transaction_boundaries(self):
        connection = self.repository.connection_facade()
        cursor = connection.cursor()

        cursor.execute(
            f'INSERT INTO "{self.schema}".items (value) VALUES (%s) RETURNING id',
            (10,),
        )
        item_id = cursor.fetchone()[0]
        connection.commit()

        cursor.execute(
            f'SELECT value FROM "{self.schema}".items WHERE id = %s',
            (item_id,),
        )
        self.assertEqual(cursor.fetchone(), (10,))

        cursor.execute(
            f'INSERT INTO "{self.schema}".items (value) VALUES (%s)',
            (20,),
        )
        connection.rollback()
        cursor.execute(f'SELECT COUNT(*) FROM "{self.schema}".items')
        self.assertEqual(cursor.fetchone()[0], 1)

    def test_public_db_api_uses_the_repository_pool(self):
        from bot.infra import repository as repository_module

        connection_info = parse_dsn(os.environ["TEST_DATABASE_URL"])
        database_env = {
            "DB_NAME": connection_info["dbname"],
            "DB_USER": connection_info["user"],
            "DB_PASS": connection_info["password"],
            "DB_HOST": connection_info["host"],
            "DB_PORT": connection_info["port"],
            "DB_POOL_MIN_SIZE": "1",
            "DB_POOL_MAX_SIZE": "3",
        }
        sys.modules.pop("bot.infra.db", None)
        repository_module._repository = None
        with patch.dict(os.environ, database_env):
            db = importlib.import_module("bot.infra.db")
            try:
                db.migrate_add_notification_flags()
                site_id = db.add_site(
                    987654321,
                    "https://repository.example",
                    "integration",
                    "pool",
                )

                self.assertEqual(
                    db.get_site_for_user(site_id, 987654321)[3],
                    "https://repository.example",
                )
                db.log_agent_check_result({
                    "job_id": "history-test",
                    "agent_id": "moscow-1",
                    "country": "RU",
                    "region": "Moscow",
                    "provider": "test",
                    "url": "https://repository.example",
                    "ok": True,
                    "http": {"ok": True, "latency_ms": 125},
                    "duration_ms": 125,
                })
                started_at = datetime.utcnow() - timedelta(minutes=5)
                db.start_site_incident(
                    site_id,
                    started_at,
                    "203.0.113.10",
                    error="timeout",
                    failure_count=2,
                )
                db.clear_site_incident(
                    site_id,
                    ended_at=datetime.utcnow(),
                    http_status=200,
                    latency_ms=125,
                    resolved_ip="203.0.113.10",
                )

                hourly_history = db.get_site_history_for_user(
                    site_id, 987654321, days=1
                )
                monthly_history = db.get_site_history_for_user(
                    site_id, 987654321, days=30
                )
                self.assertEqual(hourly_history["granularity"], "hour")
                self.assertEqual(monthly_history["granularity"], "day")
                self.assertEqual(hourly_history["summary"]["max_latency_ms"], 125)
                self.assertEqual(hourly_history["summary"]["central_incidents"], 1)
                self.assertEqual(
                    hourly_history["availability_policy"]["missing_checks"],
                    "excluded",
                )
                self.assertEqual(
                    hourly_history["incidents"][0]["failure_count"],
                    2,
                )

                self.assertTrue(
                    db.set_site_paused_by_id(site_id, 987654321, True)
                )
                self.assertTrue(db.get_sites_with_pause(987654321)[0][6])
                self.assertTrue(db.delete_site_by_id(site_id, 987654321))
            finally:
                db.repository.close()
                repository_module._repository = None
                sys.modules.pop("bot.infra.db", None)

    def test_pool_supports_concurrent_transactions(self):
        barrier = threading.Barrier(3)
        errors = []

        def insert(value):
            try:
                with self.repository.transaction() as cursor:
                    barrier.wait(timeout=2)
                    cursor.execute(
                        f'INSERT INTO "{self.schema}".items (value) VALUES (%s)',
                        (value,),
                    )
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=insert, args=(value,)) for value in range(3)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=5)

        self.assertEqual(errors, [])
        self.assertTrue(all(not thread.is_alive() for thread in threads))
        with self.repository.transaction() as cursor:
            cursor.execute(f'SELECT COUNT(*) FROM "{self.schema}".items')
            self.assertEqual(cursor.fetchone()[0], 3)


if __name__ == "__main__":
    unittest.main()
