import os
import threading
from contextlib import contextmanager
from dataclasses import dataclass

from psycopg2.pool import ThreadedConnectionPool


@dataclass(frozen=True)
class DatabaseConfig:
    dbname: str
    user: str
    password: str
    host: str
    port: str
    min_connections: int = 1
    max_connections: int = 10

    @classmethod
    def from_env(cls):
        minimum = max(1, int(os.getenv("DB_POOL_MIN_SIZE", "1")))
        maximum = max(minimum, int(os.getenv("DB_POOL_MAX_SIZE", "10")))
        return cls(
            dbname=os.getenv("DB_NAME", "devcheck"),
            user=os.getenv("DB_USER", "user"),
            password=os.getenv("DB_PASS", "password"),
            host=os.getenv("DB_HOST", "localhost"),
            port=os.getenv("DB_PORT", "5432"),
            min_connections=minimum,
            max_connections=maximum,
        )


class DatabaseRepository:
    """Owns pooled PostgreSQL connections and transaction boundaries."""

    def __init__(self, config=None, *, dsn=None, min_connections=None, max_connections=None):
        config = config or DatabaseConfig.from_env()
        minimum = (
            config.min_connections if min_connections is None else min_connections
        )
        maximum = (
            config.max_connections if max_connections is None else max_connections
        )
        if minimum < 1 or maximum < minimum:
            raise ValueError("Invalid database pool size")

        connection_args = {"dsn": dsn} if dsn else {
            "dbname": config.dbname,
            "user": config.user,
            "password": config.password,
            "host": config.host,
            "port": config.port,
        }
        self._pool = ThreadedConnectionPool(minimum, maximum, **connection_args)
        self._available = threading.BoundedSemaphore(maximum)
        self._local = threading.local()

    def _acquire(self):
        self._available.acquire()
        try:
            return self._pool.getconn()
        except Exception:
            self._available.release()
            raise

    def _release(self, connection, *, close=False):
        try:
            self._pool.putconn(connection, close=close)
        finally:
            self._available.release()

    @contextmanager
    def transaction(self):
        connection = self._acquire()
        try:
            with connection:
                with connection.cursor() as cursor:
                    yield cursor
        finally:
            self._release(connection, close=connection.closed != 0)

    def cursor_facade(self):
        return _CursorFacade(self)

    def connection_facade(self):
        return _ConnectionFacade(self)

    def _state(self):
        return getattr(self._local, "state", None)

    def _ensure_state(self):
        state = self._state()
        if state is None:
            connection = self._acquire()
            try:
                cursor = connection.cursor()
            except Exception:
                self._release(connection, close=connection.closed != 0)
                raise
            state = _OperationState(connection, cursor)
            self._local.state = state
        return state

    def _finish(self, action):
        state = self._state()
        if state is None:
            return
        close = False
        try:
            action(state.connection)
        except Exception:
            try:
                state.connection.rollback()
            except Exception:
                close = True
            raise
        finally:
            try:
                state.cursor.close()
            finally:
                del self._local.state
                self._release(state.connection, close=close or state.connection.closed != 0)

    def close(self):
        state = self._state()
        if state is not None:
            self._finish(lambda connection: connection.rollback())
        self._pool.closeall()


@dataclass
class _OperationState:
    connection: object
    cursor: object
    dirty: bool = False


def _is_read_only(cursor, query):
    status = getattr(cursor, "statusmessage", "")
    if isinstance(status, str) and status:
        return status.upper().startswith(("SELECT", "SHOW", "EXPLAIN"))

    statement = str(query).lstrip().upper()
    return statement.startswith(("SELECT", "SHOW", "EXPLAIN", "WITH"))


class _CursorFacade:
    """Compatibility cursor that scopes pooled connections to one operation."""

    def __init__(self, repository):
        self._repository = repository
        self._local = threading.local()

    def execute(self, query, params=None):
        state = self._repository._ensure_state()
        try:
            state.cursor.execute(query, params)
            state.dirty = state.dirty or not _is_read_only(state.cursor, query)
            self._local.rowcount = state.cursor.rowcount
            return self
        except Exception:
            self._repository._finish(lambda connection: connection.rollback())
            raise

    def fetchone(self):
        state = self._repository._state()
        if state is None:
            raise RuntimeError("fetchone() called without an active query")
        try:
            row = state.cursor.fetchone()
            self._local.rowcount = state.cursor.rowcount
        except Exception:
            self._repository._finish(lambda connection: connection.rollback())
            raise
        if not state.dirty:
            self._repository._finish(lambda connection: connection.rollback())
        return row

    def fetchall(self):
        state = self._repository._state()
        if state is None:
            raise RuntimeError("fetchall() called without an active query")
        try:
            rows = state.cursor.fetchall()
            self._local.rowcount = state.cursor.rowcount
        except Exception:
            self._repository._finish(lambda connection: connection.rollback())
            raise
        if not state.dirty:
            self._repository._finish(lambda connection: connection.rollback())
        return rows

    @property
    def rowcount(self):
        state = self._repository._state()
        return state.cursor.rowcount if state is not None else getattr(self._local, "rowcount", -1)


class _ConnectionFacade:
    """Compatibility commit/rollback surface used by the existing DB API."""

    def __init__(self, repository):
        self._repository = repository

    def cursor(self):
        return self._repository.cursor_facade()

    def commit(self):
        self._repository._finish(lambda connection: connection.commit())

    def rollback(self):
        self._repository._finish(lambda connection: connection.rollback())

    def close(self):
        self._repository.close()


_repository = None
_repository_lock = threading.Lock()


def get_repository():
    global _repository
    if _repository is None:
        with _repository_lock:
            if _repository is None:
                _repository = DatabaseRepository()
    return _repository
