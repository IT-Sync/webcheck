import threading
import unittest
from unittest.mock import MagicMock, patch

from bot.infra.repository import DatabaseConfig, DatabaseRepository


class DatabaseConfigTest(unittest.TestCase):
    def test_pool_settings_are_bounded_and_ordered(self):
        with patch.dict(
            "os.environ",
            {"DB_POOL_MIN_SIZE": "3", "DB_POOL_MAX_SIZE": "2"},
            clear=True,
        ):
            config = DatabaseConfig.from_env()

        self.assertEqual(config.min_connections, 3)
        self.assertEqual(config.max_connections, 3)


class RepositoryFacadeTest(unittest.TestCase):
    def setUp(self):
        pool_patcher = patch("bot.infra.repository.ThreadedConnectionPool")
        self.addCleanup(pool_patcher.stop)
        pool_factory = pool_patcher.start()
        self.pool = pool_factory.return_value
        self.connection = MagicMock()
        self.connection.closed = 0
        self.cursor = MagicMock()
        self.connection.cursor.return_value = self.cursor
        self.pool.getconn.return_value = self.connection
        self.repository = DatabaseRepository()
        self.facade = self.repository.connection_facade()
        self.compat_cursor = self.facade.cursor()

    def test_read_returns_connection_after_fetch(self):
        self.cursor.fetchone.return_value = (42,)

        self.compat_cursor.execute("SELECT value FROM example")
        result = self.compat_cursor.fetchone()

        self.assertEqual(result, (42,))
        self.connection.rollback.assert_called_once_with()
        self.pool.putconn.assert_called_once_with(self.connection, close=False)

    def test_write_keeps_connection_until_commit(self):
        self.cursor.fetchone.return_value = (7,)

        self.compat_cursor.execute("INSERT INTO example VALUES (1) RETURNING id")
        self.assertEqual(self.compat_cursor.fetchone(), (7,))
        self.pool.putconn.assert_not_called()

        self.facade.commit()

        self.connection.commit.assert_called_once_with()
        self.pool.putconn.assert_called_once_with(self.connection, close=False)

    def test_execute_error_rolls_back_and_returns_connection(self):
        self.cursor.execute.side_effect = RuntimeError("database error")

        with self.assertRaisesRegex(RuntimeError, "database error"):
            self.compat_cursor.execute("UPDATE example SET value = 1")

        self.connection.rollback.assert_called_once_with()
        self.pool.putconn.assert_called_once_with(self.connection, close=False)

    def test_cursor_creation_error_returns_connection(self):
        self.connection.cursor.side_effect = RuntimeError("cursor error")

        with self.assertRaisesRegex(RuntimeError, "cursor error"):
            self.compat_cursor.execute("SELECT 1")

        self.pool.putconn.assert_called_once_with(self.connection, close=False)

    def test_data_modifying_cte_stays_checked_out_until_commit(self):
        self.cursor.statusmessage = "DELETE 1"
        self.cursor.fetchone.return_value = (1,)

        self.compat_cursor.execute(
            "WITH deleted AS (DELETE FROM example RETURNING id) SELECT id FROM deleted"
        )
        self.assertEqual(self.compat_cursor.fetchone(), (1,))
        self.pool.putconn.assert_not_called()

        self.facade.commit()

        self.connection.commit.assert_called_once_with()
        self.pool.putconn.assert_called_once_with(self.connection, close=False)

    def test_threads_checkout_independent_connections(self):
        connections = [MagicMock(), MagicMock()]
        for connection in connections:
            connection.closed = 0
            cursor = MagicMock()
            cursor.fetchone.return_value = (1,)
            connection.cursor.return_value = cursor
        self.pool.getconn.side_effect = connections
        barrier = threading.Barrier(2)

        def read_value():
            cursor = self.facade.cursor()
            cursor.execute("SELECT 1")
            barrier.wait()
            cursor.fetchone()

        threads = [threading.Thread(target=read_value) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=2)

        self.assertTrue(all(not thread.is_alive() for thread in threads))
        self.assertEqual(self.pool.getconn.call_count, 2)
        self.assertEqual(self.pool.putconn.call_count, 2)


if __name__ == "__main__":
    unittest.main()
