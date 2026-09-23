import importlib
import os
import sys
import threading
import unittest
from unittest.mock import patch
from uuid import uuid4

from psycopg2.extensions import parse_dsn

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
