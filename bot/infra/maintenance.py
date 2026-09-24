import os
from dataclasses import dataclass
from datetime import datetime, timedelta

import psycopg2


@dataclass(frozen=True)
class MaintenanceSettings:
    enabled: bool
    agent_result_days: int
    user_log_days: int
    bot_message_days: int
    event_days: int
    batch_size: int
    max_batches: int
    agent_hourly_days: int = 30

    @classmethod
    def from_env(cls):
        return cls(
            enabled=os.getenv("DB_MAINTENANCE_ENABLED", "0") == "1",
            agent_result_days=_positive_int("AGENT_RESULT_RETENTION_DAYS", 7),
            user_log_days=_positive_int("USER_LOG_RETENTION_DAYS", 90),
            bot_message_days=_positive_int("BOT_MESSAGE_RETENTION_DAYS", 90),
            event_days=_positive_int("EVENT_RETENTION_DAYS", 365),
            batch_size=_bounded_int("DB_CLEANUP_BATCH_SIZE", 5000, 100, 50000),
            max_batches=_bounded_int("DB_CLEANUP_MAX_BATCHES", 10, 1, 100),
            agent_hourly_days=_positive_int("AGENT_HOURLY_RETENTION_DAYS", 30),
        )


def _positive_int(name, default):
    return max(1, int(os.getenv(name, str(default))))


def _bounded_int(name, default, minimum, maximum):
    return min(maximum, max(minimum, int(os.getenv(name, str(default)))))


def _connect():
    return psycopg2.connect(
        dbname=os.getenv("DB_NAME", "devcheck"),
        user=os.getenv("DB_USER", "user"),
        password=os.getenv("DB_PASS", "password"),
        host=os.getenv("DB_HOST", "localhost"),
        port=os.getenv("DB_PORT", "5432"),
    )


def _archive_agent_batch(cursor, cutoff, batch_size):
    cursor.execute(
        """
        WITH doomed AS MATERIALIZED (
            SELECT id, agent_id, country, region, url, ok, http, created_at
            FROM agent_check_results
            WHERE created_at < %s
            ORDER BY created_at, id
            LIMIT %s
            FOR UPDATE SKIP LOCKED
        ), archived AS (
            INSERT INTO agent_check_hourly (
                bucket_start, url, agent_id, country, region, checks,
                successful_checks, latency_sum_ms, latency_samples,
                max_latency_ms
            )
            SELECT date_trunc('hour', created_at), url, agent_id,
                   MAX(country), MAX(region), COUNT(*),
                   COUNT(*) FILTER (WHERE ok),
                   COALESCE(SUM(
                       CASE WHEN (http->>'latency_ms') ~ '^[0-9]+$'
                            THEN (http->>'latency_ms')::bigint ELSE 0 END
                   ), 0),
                   COUNT(*) FILTER (
                       WHERE (http->>'latency_ms') ~ '^[0-9]+$'
                   ),
                   MAX(
                       CASE WHEN (http->>'latency_ms') ~ '^[0-9]+$'
                            THEN (http->>'latency_ms')::integer END
                   )
            FROM doomed
            GROUP BY date_trunc('hour', created_at), url, agent_id
            ON CONFLICT (bucket_start, url, agent_id) DO UPDATE SET
                country = COALESCE(EXCLUDED.country, agent_check_hourly.country),
                region = COALESCE(EXCLUDED.region, agent_check_hourly.region),
                checks = agent_check_hourly.checks + EXCLUDED.checks,
                successful_checks = agent_check_hourly.successful_checks + EXCLUDED.successful_checks,
                latency_sum_ms = agent_check_hourly.latency_sum_ms + EXCLUDED.latency_sum_ms,
                latency_samples = agent_check_hourly.latency_samples + EXCLUDED.latency_samples,
                max_latency_ms = GREATEST(agent_check_hourly.max_latency_ms, EXCLUDED.max_latency_ms)
            RETURNING 1
        )
        DELETE FROM agent_check_results
        WHERE id IN (SELECT id FROM doomed)
        """,
        (cutoff, batch_size),
    )
    return cursor.rowcount


def _archive_hourly_batch(cursor, cutoff, batch_size):
    cursor.execute(
        """
        WITH doomed AS MATERIALIZED (
            SELECT bucket_start, url, agent_id, country, region, checks,
                   successful_checks, latency_sum_ms, latency_samples,
                   max_latency_ms
            FROM agent_check_hourly
            WHERE bucket_start < %s
            ORDER BY bucket_start, url, agent_id
            LIMIT %s
            FOR UPDATE SKIP LOCKED
        ), archived AS (
            INSERT INTO agent_check_daily (
                bucket_start, url, agent_id, country, region, checks,
                successful_checks, latency_sum_ms, latency_samples,
                max_latency_ms
            )
            SELECT date_trunc('day', bucket_start), url, agent_id,
                   MAX(country), MAX(region), SUM(checks),
                   SUM(successful_checks), SUM(latency_sum_ms),
                   SUM(latency_samples), MAX(max_latency_ms)
            FROM doomed
            GROUP BY date_trunc('day', bucket_start), url, agent_id
            ON CONFLICT (bucket_start, url, agent_id) DO UPDATE SET
                country = COALESCE(EXCLUDED.country, agent_check_daily.country),
                region = COALESCE(EXCLUDED.region, agent_check_daily.region),
                checks = agent_check_daily.checks + EXCLUDED.checks,
                successful_checks = (
                    agent_check_daily.successful_checks
                    + EXCLUDED.successful_checks
                ),
                latency_sum_ms = (
                    agent_check_daily.latency_sum_ms
                    + EXCLUDED.latency_sum_ms
                ),
                latency_samples = (
                    agent_check_daily.latency_samples
                    + EXCLUDED.latency_samples
                ),
                max_latency_ms = GREATEST(
                    agent_check_daily.max_latency_ms,
                    EXCLUDED.max_latency_ms
                )
            RETURNING 1
        )
        DELETE FROM agent_check_hourly
        WHERE (bucket_start, url, agent_id) IN (
            SELECT bucket_start, url, agent_id FROM doomed
        )
        """,
        (cutoff, batch_size),
    )
    return cursor.rowcount


def _require_cleanup_index(cursor):
    cursor.execute(
        """
        SELECT COALESCE((
            SELECT index_info.indisvalid AND index_info.indisready
            FROM pg_index AS index_info
            WHERE index_info.indexrelid =
                  to_regclass('public.idx_agent_check_results_created_at')
        ), FALSE)
        """
    )
    if not cursor.fetchone()[0]:
        raise RuntimeError(
            "Create a valid idx_agent_check_results_created_at concurrently before enabling maintenance"
        )


def _delete_batch(cursor, table, cutoff, batch_size):
    if table not in {"user_logs", "bot_messages", "events"}:
        raise ValueError("Unsupported cleanup table")
    cursor.execute(
        f"""
        DELETE FROM {table}
        WHERE id IN (
            SELECT id FROM {table}
            WHERE created_at < %s
            ORDER BY created_at, id
            LIMIT %s
            FOR UPDATE SKIP LOCKED
        )
        """,
        (cutoff, batch_size),
    )
    return cursor.rowcount


def run_database_maintenance(settings=None, now=None):
    settings = settings or MaintenanceSettings.from_env()
    if not settings.enabled:
        return {"enabled": False, "deleted": {}}

    now = now or datetime.utcnow()
    deleted = {
        "agent_check_results": 0,
        "agent_check_hourly": 0,
        "user_logs": 0,
        "bot_messages": 0,
        "events": 0,
    }
    connection = _connect()
    try:
        with connection:
            with connection.cursor() as cursor:
                _require_cleanup_index(cursor)
                agent_cutoff = now - timedelta(days=settings.agent_result_days)
                for _ in range(settings.max_batches):
                    count = _archive_agent_batch(cursor, agent_cutoff, settings.batch_size)
                    deleted["agent_check_results"] += count
                    if count < settings.batch_size:
                        break

                hourly_cutoff = now - timedelta(days=settings.agent_hourly_days)
                for _ in range(settings.max_batches):
                    count = _archive_hourly_batch(
                        cursor,
                        hourly_cutoff,
                        settings.batch_size,
                    )
                    deleted["agent_check_hourly"] += count
                    if count < settings.batch_size:
                        break
                retention = {
                    "user_logs": settings.user_log_days,
                    "bot_messages": settings.bot_message_days,
                    "events": settings.event_days,
                }
                for table, days in retention.items():
                    cutoff = now - timedelta(days=days)
                    for _ in range(settings.max_batches):
                        count = _delete_batch(cursor, table, cutoff, settings.batch_size)
                        deleted[table] += count
                        if count < settings.batch_size:
                            break
    finally:
        connection.close()

    return {"enabled": True, "deleted": deleted}
