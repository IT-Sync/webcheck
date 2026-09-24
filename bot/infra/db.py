from datetime import datetime, timedelta
import csv
import json
from psycopg2.extras import Json

from bot.infra.repository import get_repository

UNSET = object()

repository = get_repository()
conn = repository.connection_facade()
c = conn.cursor()

# Таблицы
c.execute('''CREATE TABLE IF NOT EXISTS sites (
    id SERIAL PRIMARY KEY,
    user_id BIGINT,
    username TEXT,
    url TEXT,
    last_status TEXT,
    last_checked TIMESTAMP
)''')

c.execute('''CREATE TABLE IF NOT EXISTS events (
    id SERIAL PRIMARY KEY,
    url TEXT,
    message TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)''')

c.execute('''CREATE TABLE IF NOT EXISTS user_logs (
    id SERIAL PRIMARY KEY,
    user_id BIGINT,
    username TEXT,
    action TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)''')

c.execute('''CREATE TABLE IF NOT EXISTS bot_messages (
    id SERIAL PRIMARY KEY,
    user_id BIGINT,
    source TEXT,
    status TEXT,
    error TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)''')

c.execute('''CREATE TABLE IF NOT EXISTS agent_check_results (
    id SERIAL PRIMARY KEY,
    job_id TEXT,
    agent_id TEXT,
    country TEXT,
    region TEXT,
    provider TEXT,
    url TEXT,
    ok BOOLEAN,
    http JSONB,
    ssl_days INTEGER,
    domain_days INTEGER,
    registrar TEXT,
    contact_url TEXT,
    error TEXT,
    duration_ms INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)''')

c.execute('''CREATE TABLE IF NOT EXISTS agent_check_hourly (
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
)''')

c.execute('''CREATE TABLE IF NOT EXISTS agent_check_daily (
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
)''')

c.execute('''CREATE TABLE IF NOT EXISTS central_incidents (
    id BIGSERIAL PRIMARY KEY,
    site_id INTEGER NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
    url TEXT NOT NULL,
    started_at TIMESTAMP NOT NULL,
    ended_at TIMESTAMP,
    failure_count INTEGER NOT NULL DEFAULT 1,
    start_error TEXT,
    start_http_status INTEGER,
    start_latency_ms INTEGER,
    start_resolved_ip TEXT,
    end_http_status INTEGER,
    end_latency_ms INTEGER,
    end_resolved_ip TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
)''')

c.execute('''CREATE TABLE IF NOT EXISTS feedback_conversations (
    id SERIAL PRIMARY KEY,
    user_id BIGINT UNIQUE NOT NULL,
    username TEXT,
    waiting_for_user BOOLEAN NOT NULL DEFAULT FALSE,
    active_media_group_id TEXT,
    status TEXT NOT NULL DEFAULT 'open',
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_message_at TIMESTAMP
)''')

c.execute('''CREATE TABLE IF NOT EXISTS feedback_messages (
    id BIGSERIAL PRIMARY KEY,
    conversation_id INTEGER NOT NULL REFERENCES feedback_conversations(id) ON DELETE CASCADE,
    sender TEXT NOT NULL,
    message_text TEXT NOT NULL,
    telegram_message_id BIGINT,
    media_type TEXT,
    telegram_file_id TEXT,
    telegram_file_unique_id TEXT,
    file_name TEXT,
    mime_type TEXT,
    file_size BIGINT,
    media_group_id TEXT,
    is_read BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
)''')

conn.commit()

# Методы
def add_site(user_id, url, username=None, site_group=""):
    c.execute(
        "INSERT INTO sites (user_id, username, url, site_group) VALUES (%s, %s, %s, %s) RETURNING id",
        (user_id, username, url, site_group),
    )
    site_id = c.fetchone()[0]
    conn.commit()
    return site_id

def get_sites(user_id):
    c.execute("SELECT * FROM sites WHERE user_id = %s", (user_id,))
    return c.fetchall()

def get_sites_with_pause(user_id):
    c.execute(
        """
        SELECT id, user_id, username, url, last_status, last_checked,
               (COALESCE(is_paused, FALSE) OR (paused_until IS NOT NULL AND paused_until > %s)) AS is_paused_now,
               COALESCE(site_group, '')
        FROM sites
        WHERE user_id = %s
        ORDER BY id
        """,
        (datetime.utcnow(), user_id)
    )
    return c.fetchall()

def get_site_by_id(site_id):
    c.execute("SELECT * FROM sites WHERE id = %s", (site_id,))
    return c.fetchone()

def get_site_for_user(site_id, user_id):
    c.execute("SELECT * FROM sites WHERE id = %s AND user_id = %s", (site_id, user_id))
    return c.fetchone()

def get_site_by_url_for_user(user_id, url):
    c.execute("SELECT * FROM sites WHERE user_id = %s AND url = %s", (user_id, url))
    return c.fetchone()

def delete_site(user_id, url):
    c.execute("DELETE FROM sites WHERE user_id = %s AND url = %s", (user_id, url))
    conn.commit()
    return c.rowcount > 0

def delete_site_by_id(site_id, user_id):
    c.execute("DELETE FROM sites WHERE id = %s AND user_id = %s", (site_id, user_id))
    conn.commit()
    return c.rowcount > 0

def set_site_paused_by_id(site_id, user_id, paused):
    if paused:
        c.execute(
            "UPDATE sites SET is_paused = %s WHERE id = %s AND user_id = %s",
            (paused, site_id, user_id)
        )
    else:
        c.execute(
            "UPDATE sites SET is_paused = %s, paused_until = NULL WHERE id = %s AND user_id = %s",
            (paused, site_id, user_id)
        )
    conn.commit()
    return c.rowcount > 0

def set_site_paused_until_by_id(site_id, user_id, paused_until):
    c.execute(
        "UPDATE sites SET paused_until = %s WHERE id = %s AND user_id = %s",
        (paused_until, site_id, user_id)
    )
    conn.commit()
    return c.rowcount > 0


def set_site_group_by_id(site_id, user_id, site_group):
    c.execute(
        "UPDATE sites SET site_group = %s WHERE id = %s AND user_id = %s",
        (site_group, site_id, user_id),
    )
    conn.commit()
    return c.rowcount > 0

def set_site_paused(user_id, url, paused):
    if paused:
        c.execute(
            "UPDATE sites SET is_paused = %s WHERE user_id = %s AND url = %s",
            (paused, user_id, url)
        )
    else:
        c.execute(
            "UPDATE sites SET is_paused = %s, paused_until = NULL WHERE user_id = %s AND url = %s",
            (paused, user_id, url)
        )
    conn.commit()
    return c.rowcount > 0

def get_site_pause_status(site_id):
    c.execute("SELECT is_paused, paused_until FROM sites WHERE id = %s", (site_id,))
    row = c.fetchone()
    if not row:
        return False
    paused_until = row[1]
    return bool(row[0]) or (paused_until is not None and paused_until > datetime.utcnow())

def admin_delete_site_by_id(site_id):
    c.execute("DELETE FROM sites WHERE id = %s", (site_id,))
    conn.commit()
    return c.rowcount > 0

def delete_user_sites(user_id):
    """Удаляет только сайты пользователя, без очистки логов."""
    c.execute("DELETE FROM sites WHERE user_id = %s", (user_id,))
    deleted = c.rowcount
    conn.commit()
    return deleted

def delete_user_data(user_id):
    """Полностью удаляет пользователя: сайты и его действия в логах."""
    c.execute("DELETE FROM sites WHERE user_id = %s", (user_id,))
    sites_deleted = c.rowcount
    c.execute("DELETE FROM user_logs WHERE user_id = %s", (user_id,))
    logs_deleted = c.rowcount
    c.execute("DELETE FROM bot_messages WHERE user_id = %s", (user_id,))
    messages_deleted = c.rowcount
    c.execute("DELETE FROM feedback_conversations WHERE user_id = %s", (user_id,))
    conn.commit()
    return sites_deleted, logs_deleted, messages_deleted


def start_feedback_waiting(user_id, username=None):
    try:
        c.execute(
            """
            INSERT INTO feedback_conversations (
                user_id, username, waiting_for_user, status, updated_at
            )
            VALUES (%s, %s, TRUE, 'open', %s)
            ON CONFLICT (user_id) DO UPDATE SET
                username = COALESCE(EXCLUDED.username, feedback_conversations.username),
                waiting_for_user = TRUE,
                active_media_group_id = NULL,
                status = 'open',
                updated_at = EXCLUDED.updated_at
            RETURNING id
            """,
            (user_id, username, datetime.utcnow()),
        )
        conversation_id = c.fetchone()[0]
        conn.commit()
        return conversation_id
    except Exception:
        conn.rollback()
        raise


def cancel_feedback_waiting(user_id):
    try:
        c.execute(
            """
            UPDATE feedback_conversations
            SET waiting_for_user = FALSE,
                active_media_group_id = NULL,
                updated_at = %s
            WHERE user_id = %s AND waiting_for_user = TRUE
            """,
            (datetime.utcnow(), user_id),
        )
        updated = c.rowcount > 0
        conn.commit()
        return updated
    except Exception:
        conn.rollback()
        raise


def is_feedback_waiting(user_id, media_group_id=None):
    c.execute(
        """
        SELECT waiting_for_user OR (
            %s IS NOT NULL AND active_media_group_id = %s
        )
        FROM feedback_conversations
        WHERE user_id = %s
        """,
        (media_group_id, media_group_id, user_id),
    )
    row = c.fetchone()
    return bool(row and row[0])


def add_user_feedback_message(
    user_id,
    username,
    message_text,
    *,
    telegram_message_id=None,
    media_type=None,
    telegram_file_id=None,
    telegram_file_unique_id=None,
    file_name=None,
    mime_type=None,
    file_size=None,
    media_group_id=None,
):
    now = datetime.utcnow()
    try:
        c.execute(
            """
            UPDATE feedback_conversations
            SET username = COALESCE(%s, username),
                waiting_for_user = FALSE,
                status = 'open',
                updated_at = %s,
                last_message_at = %s,
                active_media_group_id = %s
            WHERE user_id = %s AND (
                waiting_for_user = TRUE
                OR (%s IS NOT NULL AND active_media_group_id = %s)
            )
            RETURNING id
            """,
            (
                username, now, now, media_group_id, user_id,
                media_group_id, media_group_id,
            ),
        )
        row = c.fetchone()
        if not row:
            conn.rollback()
            return None
        conversation_id = row[0]
        c.execute(
            """
            INSERT INTO feedback_messages (
                conversation_id, sender, message_text, telegram_message_id,
                media_type, telegram_file_id, telegram_file_unique_id,
                file_name, mime_type, file_size, media_group_id,
                is_read, created_at
            )
            VALUES (
                %s, 'user', %s, %s, %s, %s, %s, %s, %s, %s, %s,
                FALSE, %s
            )
            RETURNING id
            """,
            (
                conversation_id, message_text, telegram_message_id,
                media_type, telegram_file_id, telegram_file_unique_id,
                file_name, mime_type, file_size, media_group_id, now,
            ),
        )
        message_id = c.fetchone()[0]
        conn.commit()
        return {"conversation_id": conversation_id, "message_id": message_id}
    except Exception:
        conn.rollback()
        raise


def get_feedback_conversations():
    c.execute(
        """
        SELECT conversation.id, conversation.user_id, conversation.username,
               conversation.status, conversation.waiting_for_user,
               conversation.created_at, conversation.updated_at,
               conversation.last_message_at,
               COALESCE(messages.unread_count, 0),
               latest.sender, latest.message_text, latest.created_at,
               latest.media_type, latest.file_name
        FROM feedback_conversations AS conversation
        LEFT JOIN LATERAL (
            SELECT COUNT(*) FILTER (
                WHERE sender = 'user' AND is_read = FALSE
            ) AS unread_count
            FROM feedback_messages
            WHERE conversation_id = conversation.id
        ) AS messages ON TRUE
        LEFT JOIN LATERAL (
            SELECT sender, message_text, created_at, media_type, file_name
            FROM feedback_messages
            WHERE conversation_id = conversation.id
            ORDER BY created_at DESC, id DESC
            LIMIT 1
        ) AS latest ON TRUE
        WHERE conversation.last_message_at IS NOT NULL
        ORDER BY COALESCE(messages.unread_count, 0) DESC,
                 conversation.last_message_at DESC NULLS LAST
        """
    )
    return [
        {
            "id": row[0],
            "user_id": row[1],
            "username": row[2],
            "status": row[3],
            "waiting_for_user": row[4],
            "created_at": row[5],
            "updated_at": row[6],
            "last_message_at": row[7],
            "unread_count": row[8],
            "last_sender": row[9],
            "last_message": row[10],
            "last_message_created_at": row[11],
            "last_media_type": row[12],
            "last_file_name": row[13],
        }
        for row in c.fetchall()
    ]


def get_feedback_conversation(conversation_id):
    c.execute(
        """
        SELECT id, user_id, username, status, waiting_for_user,
               created_at, updated_at, last_message_at
        FROM feedback_conversations
        WHERE id = %s
        """,
        (conversation_id,),
    )
    row = c.fetchone()
    if not row:
        return None
    return {
        "id": row[0],
        "user_id": row[1],
        "username": row[2],
        "status": row[3],
        "waiting_for_user": row[4],
        "created_at": row[5],
        "updated_at": row[6],
        "last_message_at": row[7],
    }


def get_feedback_messages(conversation_id):
    c.execute(
        """
        SELECT id, sender, message_text, is_read, created_at,
               telegram_message_id, media_type, telegram_file_id,
               telegram_file_unique_id, file_name, mime_type, file_size,
               media_group_id
        FROM feedback_messages
        WHERE conversation_id = %s
        ORDER BY created_at, id
        """,
        (conversation_id,),
    )
    return [
        {
            "id": row[0],
            "sender": row[1],
            "message_text": row[2],
            "is_read": row[3],
            "created_at": row[4],
            "telegram_message_id": row[5],
            "media_type": row[6],
            "telegram_file_id": row[7],
            "telegram_file_unique_id": row[8],
            "file_name": row[9],
            "mime_type": row[10],
            "file_size": row[11],
            "media_group_id": row[12],
        }
        for row in c.fetchall()
    ]


def get_feedback_message(message_id):
    c.execute(
        """
        SELECT message.id, message.conversation_id, message.sender,
               message.message_text, message.media_type,
               message.telegram_file_id, message.file_name,
               message.mime_type, message.file_size, message.created_at,
               conversation.user_id
        FROM feedback_messages AS message
        JOIN feedback_conversations AS conversation
          ON conversation.id = message.conversation_id
        WHERE message.id = %s
        """,
        (message_id,),
    )
    row = c.fetchone()
    if not row:
        return None
    return {
        "id": row[0],
        "conversation_id": row[1],
        "sender": row[2],
        "message_text": row[3],
        "media_type": row[4],
        "telegram_file_id": row[5],
        "file_name": row[6],
        "mime_type": row[7],
        "file_size": row[8],
        "created_at": row[9],
        "user_id": row[10],
    }


def mark_feedback_read(conversation_id):
    c.execute(
        """
        UPDATE feedback_messages
        SET is_read = TRUE
        WHERE conversation_id = %s AND sender = 'user' AND is_read = FALSE
        """,
        (conversation_id,),
    )
    conn.commit()


def add_admin_feedback_message(conversation_id, message_text):
    now = datetime.utcnow()
    try:
        c.execute(
            """
            INSERT INTO feedback_messages (
                conversation_id, sender, message_text, is_read, created_at
            )
            VALUES (%s, 'admin', %s, TRUE, %s)
            RETURNING id
            """,
            (conversation_id, message_text, now),
        )
        message_id = c.fetchone()[0]
        c.execute(
            """
            UPDATE feedback_conversations
            SET status = 'answered', updated_at = %s, last_message_at = %s
            WHERE id = %s
            """,
            (now, now, conversation_id),
        )
        conn.commit()
        return message_id
    except Exception:
        conn.rollback()
        raise

def get_all_sites(full=False):
    if full:
        c.execute("SELECT user_id, url, username FROM sites ORDER BY user_id, id")
    else:
        c.execute("SELECT DISTINCT user_id, url FROM sites ORDER BY user_id, url")
    return c.fetchall()

def get_admin_users():
    c.execute("""
        SELECT
            user_id,
            MAX(username) FILTER (WHERE username IS NOT NULL AND username <> '') AS username,
            COUNT(*) FILTER (WHERE source = 'site') AS site_count,
            MAX(last_checked) AS last_checked,
            MAX(last_action_at) AS last_action_at
        FROM (
            SELECT user_id, username, 'site' AS source, last_checked, NULL::timestamp AS last_action_at
            FROM sites
            UNION ALL
            SELECT user_id, username, 'log' AS source, NULL::timestamp AS last_checked, created_at AS last_action_at
            FROM user_logs
        ) rows
        GROUP BY user_id
        ORDER BY last_action_at DESC NULLS LAST, user_id
    """)
    return [
        {
            "user_id": row[0],
            "username": row[1],
            "site_count": row[2],
            "last_checked": row[3],
            "last_action_at": row[4],
        }
        for row in c.fetchall()
    ]

def get_admin_user(user_id):
    c.execute("""
        SELECT
            user_id,
            MAX(username) FILTER (WHERE username IS NOT NULL AND username <> '') AS username,
            COUNT(*) FILTER (WHERE source = 'site') AS site_count,
            MAX(last_checked) AS last_checked,
            MAX(last_action_at) AS last_action_at
        FROM (
            SELECT user_id, username, 'site' AS source, last_checked, NULL::timestamp AS last_action_at
            FROM sites
            WHERE user_id = %s
            UNION ALL
            SELECT user_id, username, 'log' AS source, NULL::timestamp AS last_checked, created_at AS last_action_at
            FROM user_logs
            WHERE user_id = %s
        ) rows
        GROUP BY user_id
    """, (user_id, user_id))
    row = c.fetchone()
    if not row:
        return {
            "user_id": user_id,
            "username": None,
            "site_count": 0,
            "last_checked": None,
            "last_action_at": None,
        }
    return {
        "user_id": row[0],
        "username": row[1],
        "site_count": row[2],
        "last_checked": row[3],
        "last_action_at": row[4],
    }

def get_admin_stats():
    c.execute("SELECT COUNT(DISTINCT user_id), COUNT(*) FROM sites")
    users_with_sites, site_count = c.fetchone()
    c.execute("SELECT COUNT(DISTINCT user_id), COUNT(*) FROM user_logs WHERE created_at > %s", (datetime.utcnow() - timedelta(days=14),))
    active_users_14d, logs_14d = c.fetchone()
    c.execute("""
        SELECT
            COUNT(*) FILTER (
                WHERE COALESCE(is_paused, FALSE) = FALSE
                  AND (paused_until IS NULL OR paused_until <= %s)
            ),
            COUNT(*) FILTER (
                WHERE COALESCE(is_paused, FALSE) = TRUE
                   OR (paused_until IS NOT NULL AND paused_until > %s)
            )
        FROM sites
    """, (datetime.utcnow(), datetime.utcnow()))
    active_sites, paused_sites = c.fetchone()
    c.execute("SELECT COUNT(*) FROM events WHERE created_at > %s", (datetime.utcnow() - timedelta(days=14),))
    events_14d = c.fetchone()[0]
    c.execute("""
        SELECT
            COUNT(*) FILTER (WHERE status = 'sent'),
            COUNT(*) FILTER (WHERE status <> 'sent')
        FROM bot_messages
        WHERE created_at > %s
    """, (datetime.utcnow() - timedelta(days=14),))
    sent_messages_14d, failed_messages_14d = c.fetchone()
    return {
        "users_with_sites": users_with_sites or 0,
        "site_count": site_count or 0,
        "active_sites": active_sites or 0,
        "paused_sites": paused_sites or 0,
        "active_users_14d": active_users_14d or 0,
        "logs_14d": logs_14d or 0,
        "events_14d": events_14d or 0,
        "sent_messages_14d": sent_messages_14d or 0,
        "failed_messages_14d": failed_messages_14d or 0,
    }

def get_admin_usage_stats(days=14):
    since = datetime.utcnow().date() - timedelta(days=days - 1)
    c.execute("""
        SELECT created_at::date, COUNT(*), COUNT(DISTINCT user_id)
        FROM user_logs
        WHERE created_at::date >= %s
        GROUP BY created_at::date
        ORDER BY created_at::date
    """, (since,))
    rows = {row[0]: {"actions": row[1], "users": row[2]} for row in c.fetchall()}
    return [
        {
            "date": since + timedelta(days=offset),
            "actions": rows.get(since + timedelta(days=offset), {}).get("actions", 0),
            "users": rows.get(since + timedelta(days=offset), {}).get("users", 0),
        }
        for offset in range(days)
    ]

def get_admin_message_stats(days=14):
    since = datetime.utcnow().date() - timedelta(days=days - 1)
    c.execute("""
        SELECT created_at::date,
               COUNT(*) FILTER (WHERE status = 'sent'),
               COUNT(*) FILTER (WHERE status <> 'sent')
        FROM bot_messages
        WHERE created_at::date >= %s
        GROUP BY created_at::date
        ORDER BY created_at::date
    """, (since,))
    rows = {row[0]: {"sent": row[1] or 0, "failed": row[2] or 0} for row in c.fetchall()}
    return [
        {
            "date": since + timedelta(days=offset),
            "sent": rows.get(since + timedelta(days=offset), {}).get("sent", 0),
            "failed": rows.get(since + timedelta(days=offset), {}).get("failed", 0),
        }
        for offset in range(days)
    ]

def get_admin_command_stats(days=14, limit=12):
    c.execute("""
        SELECT split_part(action, ' ', 1) AS command,
               COUNT(*) AS total,
               COUNT(DISTINCT user_id) AS users
        FROM user_logs
        WHERE created_at > %s
          AND action LIKE %s
        GROUP BY command
        ORDER BY total DESC, command
        LIMIT %s
    """, (datetime.utcnow() - timedelta(days=days), "/%", limit))
    return [
        {
            "command": row[0],
            "total": row[1],
            "users": row[2],
        }
        for row in c.fetchall()
    ]

def get_admin_bot_response_stats(days=14):
    c.execute("""
        SELECT source,
               COUNT(*) FILTER (WHERE status = 'sent') AS sent,
               COUNT(*) FILTER (WHERE status <> 'sent') AS failed
        FROM bot_messages
        WHERE created_at > %s
        GROUP BY source
        ORDER BY sent DESC, failed DESC, source
    """, (datetime.utcnow() - timedelta(days=days),))
    return [
        {
            "source": row[0],
            "sent": row[1] or 0,
            "failed": row[2] or 0,
        }
        for row in c.fetchall()
    ]

def get_admin_sites(user_id=None):
    params = [datetime.utcnow()]
    where = ""
    if user_id is not None:
        where = "WHERE user_id = %s"
        params.append(user_id)
    c.execute(f"""
        SELECT id, user_id, username, url, last_status, last_checked,
               (COALESCE(is_paused, FALSE) OR (paused_until IS NOT NULL AND paused_until > %s)) AS is_paused_now,
               COALESCE(site_group, '')
        FROM sites
        {where}
        ORDER BY user_id, id
    """, tuple(params))
    return [
        {
            "id": row[0],
            "user_id": row[1],
            "username": row[2],
            "url": row[3],
            "last_status": row[4],
            "last_checked": row[5],
            "is_paused": row[6],
            "site_group": row[7],
        }
        for row in c.fetchall()
    ]

def get_all_site_checks():
    c.execute("""
        SELECT id, user_id, url, incident_started_at, last_success_at,
               last_success_http_status, last_success_latency_ms, last_resolved_ip
        FROM sites
        WHERE COALESCE(is_paused, FALSE) = FALSE
          AND (paused_until IS NULL OR paused_until <= %s)
        ORDER BY id
    """, (datetime.utcnow(),))
    return c.fetchall()

def get_report_sites(user_id=None):
    params = [datetime.utcnow()]
    where = ""
    if user_id is not None:
        where = "WHERE user_id = %s"
        params.append(user_id)
    c.execute(f"""
        SELECT id, user_id, username, url, last_status, last_checked,
               (COALESCE(is_paused, FALSE) OR (paused_until IS NOT NULL AND paused_until > %s)) AS is_paused_now,
               COALESCE(site_group, '')
        FROM sites
        {where}
        ORDER BY user_id, id
    """, tuple(params))
    rows = c.fetchall()
    return [
        {
            "id": row[0],
            "user_id": row[1],
            "username": row[2],
            "url": row[3],
            "last_status": row[4],
            "last_checked": row[5],
            "is_paused": row[6],
            "site_group": row[7],
        }
        for row in rows
    ]

def update_site_status(url, status):
    c.execute("UPDATE sites SET last_status = %s, last_checked = %s WHERE url = %s", (status, datetime.utcnow(), url))
    conn.commit()

def update_site_status_by_id(site_id, status):
    c.execute(
        "UPDATE sites SET last_status = %s, last_checked = %s WHERE id = %s",
        (status, datetime.utcnow(), site_id)
    )
    conn.commit()

def update_site_success(site_id, http_status=None, latency_ms=None, resolved_ip=None):
    c.execute(
        """
        UPDATE sites
        SET last_success_at = %s,
            last_success_http_status = %s,
            last_success_latency_ms = %s,
            last_resolved_ip = COALESCE(%s, last_resolved_ip)
        WHERE id = %s
        """,
        (datetime.utcnow(), http_status, latency_ms, resolved_ip, site_id)
    )
    conn.commit()

def start_site_incident(
    site_id,
    started_at,
    resolved_ip=None,
    *,
    http_status=None,
    latency_ms=None,
    error=None,
    failure_count=1,
):
    try:
        c.execute(
            """
            UPDATE sites
            SET incident_started_at = COALESCE(incident_started_at, %s),
                last_resolved_ip = COALESCE(%s, last_resolved_ip)
            WHERE id = %s
            RETURNING incident_started_at, url
            """,
            (started_at, resolved_ip, site_id),
        )
        row = c.fetchone()
        if not row:
            conn.rollback()
            return started_at
        incident_started_at, url = row
        c.execute(
            """
            INSERT INTO central_incidents (
                site_id, url, started_at, failure_count, start_error,
                start_http_status, start_latency_ms, start_resolved_ip,
                updated_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (site_id) WHERE ended_at IS NULL DO UPDATE SET
                failure_count = GREATEST(
                    central_incidents.failure_count,
                    EXCLUDED.failure_count
                ),
                updated_at = EXCLUDED.updated_at
            """,
            (
                site_id, url, incident_started_at, failure_count, error,
                http_status, latency_ms, resolved_ip, datetime.utcnow(),
            ),
        )
        conn.commit()
        return incident_started_at
    except Exception:
        conn.rollback()
        raise


def clear_site_incident(
    site_id,
    *,
    ended_at=None,
    http_status=None,
    latency_ms=None,
    resolved_ip=None,
):
    ended_at = ended_at or datetime.utcnow()
    try:
        c.execute(
            "UPDATE sites SET incident_started_at = NULL WHERE id = %s",
            (site_id,),
        )
        c.execute(
            """
            UPDATE central_incidents
            SET ended_at = %s,
                end_http_status = %s,
                end_latency_ms = %s,
                end_resolved_ip = %s,
                updated_at = %s
            WHERE site_id = %s AND ended_at IS NULL
            """,
            (
                ended_at, http_status, latency_ms, resolved_ip,
                ended_at, site_id,
            ),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise

def get_site_statuses():
    c.execute("SELECT url, last_status FROM sites")
    return c.fetchall()

def log_event(url, message):
    c.execute("INSERT INTO events (url, message) VALUES (%s, %s)", (url, message))
    conn.commit()

def get_event_logs():
    since = datetime.utcnow() - timedelta(days=14)
    c.execute("SELECT created_at, url, message FROM events WHERE created_at > %s ORDER BY created_at DESC", (since,))
    return c.fetchall()

def get_event_logs_for_url(url):
    since = datetime.utcnow() - timedelta(days=14)
    c.execute(
        "SELECT created_at, url, message FROM events WHERE created_at > %s AND url = %s ORDER BY created_at DESC",
        (since, url)
    )
    return c.fetchall()

#def admin_delete_site(url):
#    c.execute("DELETE FROM sites WHERE url = %s", (url,))
#    conn.commit()

def admin_delete_site(user_id, url):
    c.execute("DELETE FROM sites WHERE user_id = %s AND url = %s", (user_id, url))
    conn.commit()


def log_user_action(user_id, action, username=None):
    c.execute("INSERT INTO user_logs (user_id, username, action) VALUES (%s, %s, %s)", (user_id, username, action))
    conn.commit()

def log_bot_message(user_id, source, status="sent", error=None):
    c.execute(
        "INSERT INTO bot_messages (user_id, source, status, error) VALUES (%s, %s, %s, %s)",
        (user_id, source, status, error)
    )
    conn.commit()

def log_agent_check_result(payload):
    c.execute(
        """
        INSERT INTO agent_check_results (
            job_id, agent_id, country, region, provider, url, ok, http,
            ssl_days, domain_days, registrar, contact_url, error, duration_ms
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            payload.get("job_id"),
            payload.get("agent_id"),
            payload.get("country"),
            payload.get("region"),
            payload.get("provider"),
            payload.get("url"),
            payload.get("ok"),
            Json(payload.get("http")) if payload.get("http") is not None else None,
            payload.get("ssl_days"),
            payload.get("domain_days"),
            payload.get("registrar"),
            payload.get("contact_url"),
            payload.get("error"),
            payload.get("duration_ms"),
        )
    )
    conn.commit()

def get_latest_agent_results_for_url(url, max_age_minutes=60):
    since = datetime.utcnow() - timedelta(minutes=max_age_minutes)
    c.execute(
        """
        SELECT DISTINCT ON (agent_id)
            agent_id, country, region, provider, url, ok, http, ssl_days,
            domain_days, registrar, contact_url, error, duration_ms, created_at
        FROM agent_check_results
        WHERE url = %s
          AND created_at >= %s
        ORDER BY agent_id, created_at DESC
        """,
        (url, since)
    )
    rows = c.fetchall()
    return [
        {
            "agent_id": row[0],
            "country": row[1],
            "region": row[2],
            "provider": row[3],
            "url": row[4],
            "ok": row[5],
            "http": row[6] if not isinstance(row[6], str) else json.loads(row[6]),
            "ssl_days": row[7],
            "domain_days": row[8],
            "registrar": row[9],
            "contact_url": row[10],
            "error": row[11],
            "duration_ms": row[12],
            "checked_at": row[13],
        }
        for row in rows
    ]

def get_latest_agent_results_for_urls(urls, max_age_minutes=60):
    urls = list(dict.fromkeys(url for url in urls if url))
    if not urls:
        return {}
    since = datetime.utcnow() - timedelta(minutes=max_age_minutes)
    c.execute(
        """
        SELECT DISTINCT ON (url, agent_id)
            url, agent_id, country, region, provider, ok, http, ssl_days,
            domain_days, registrar, contact_url, error, duration_ms, created_at
        FROM agent_check_results
        WHERE url = ANY(%s)
          AND created_at >= %s
        ORDER BY url, agent_id, created_at DESC
        """,
        (urls, since)
    )
    grouped = {}
    for row in c.fetchall():
        url = row[0]
        grouped.setdefault(url, []).append({
            "agent_id": row[1],
            "country": row[2],
            "region": row[3],
            "provider": row[4],
            "url": url,
            "ok": row[5],
            "http": row[6] if not isinstance(row[6], str) else json.loads(row[6]),
            "ssl_days": row[7],
            "domain_days": row[8],
            "registrar": row[9],
            "contact_url": row[10],
            "error": row[11],
            "duration_ms": row[12],
            "checked_at": row[13],
        })
    return grouped


def get_site_history_for_user(site_id, user_id, days=7):
    days = max(1, min(int(days), 90))
    site = get_site_for_user(site_id, user_id)
    if not site:
        return None

    url = site[3]
    now = datetime.utcnow()
    since = now - timedelta(days=days)
    granularity = "hour" if days <= 7 else "day"
    c.execute(
        """
        SELECT created_at, message
        FROM events
        WHERE url = %s
          AND created_at >= %s
          AND (
              message ILIKE '%%недоступен%%'
              OR message ILIKE '%%восстанов%%'
              OR message ILIKE '%%истекает%%'
              OR message ILIKE '%%продлён%%'
              OR message ILIKE '%%DOWN%%'
          )
        ORDER BY created_at DESC
        LIMIT 50
        """,
        (url, since),
    )
    events = [
        {"created_at": row[0], "message": row[1]}
        for row in c.fetchall()
    ]

    c.execute(
        """
        SELECT id, started_at, ended_at, failure_count, start_error,
               start_http_status, start_latency_ms, start_resolved_ip,
               end_http_status, end_latency_ms, end_resolved_ip
        FROM central_incidents
        WHERE site_id = %s
          AND started_at <= %s
          AND COALESCE(ended_at, %s) >= %s
        ORDER BY started_at DESC
        LIMIT 100
        """,
        (site_id, now, now, since),
    )
    incidents = []
    central_downtime_seconds = 0
    for row in c.fetchall():
        effective_start = max(row[1], since)
        effective_end = min(row[2] or now, now)
        duration_seconds = max(
            0,
            round((effective_end - effective_start).total_seconds()),
        )
        central_downtime_seconds += duration_seconds
        incidents.append({
            "id": row[0],
            "started_at": row[1],
            "ended_at": row[2],
            "duration_seconds": duration_seconds,
            "failure_count": row[3],
            "start_error": row[4],
            "start_http_status": row[5],
            "start_latency_ms": row[6],
            "start_resolved_ip": row[7],
            "end_http_status": row[8],
            "end_latency_ms": row[9],
            "end_resolved_ip": row[10],
        })

    c.execute(
        """
        WITH points AS (
            SELECT date_trunc(%s, created_at) AS bucket_start,
                   agent_id,
                   MAX(country) AS country,
                   MAX(region) AS region,
                   COUNT(*)::bigint AS checks,
                   COUNT(*) FILTER (WHERE ok)::bigint AS successful_checks,
                   COALESCE(SUM(
                       CASE WHEN (http->>'latency_ms') ~ '^[0-9]+$'
                            THEN (http->>'latency_ms')::bigint ELSE 0 END
                   ), 0)::bigint AS latency_sum_ms,
                   COUNT(*) FILTER (
                       WHERE (http->>'latency_ms') ~ '^[0-9]+$'
                   )::bigint AS latency_samples,
                   MAX(
                       CASE WHEN (http->>'latency_ms') ~ '^[0-9]+$'
                            THEN (http->>'latency_ms')::integer END
                   ) AS max_latency_ms
            FROM agent_check_results
            WHERE url = %s AND created_at >= %s
            GROUP BY 1, 2
            UNION ALL
            SELECT date_trunc(%s, bucket_start), agent_id,
                   MAX(country), MAX(region), SUM(checks),
                   SUM(successful_checks), SUM(latency_sum_ms),
                   SUM(latency_samples), MAX(max_latency_ms)
            FROM agent_check_hourly
            WHERE url = %s AND bucket_start >= %s
            GROUP BY 1, 2
            UNION ALL
            SELECT bucket_start, agent_id, country, region, checks,
                   successful_checks, latency_sum_ms, latency_samples,
                   max_latency_ms
            FROM agent_check_daily
            WHERE url = %s AND bucket_start >= %s
        )
        SELECT bucket_start, agent_id, MAX(country), MAX(region),
               SUM(checks), SUM(successful_checks), SUM(latency_sum_ms),
               SUM(latency_samples), MAX(max_latency_ms)
        FROM points
        GROUP BY bucket_start, agent_id
        ORDER BY bucket_start, agent_id
        """,
        (
            granularity, url, since,
            granularity, url, since,
            url, since,
        ),
    )
    points = []
    total_checks = 0
    successful_checks = 0
    latency_sum = 0
    latency_samples = 0
    max_latency_ms = None
    for row in c.fetchall():
        checks = int(row[4] or 0)
        successes = int(row[5] or 0)
        point_latency_sum = int(row[6] or 0)
        point_latency_samples = int(row[7] or 0)
        point_max_latency = row[8]
        total_checks += checks
        successful_checks += successes
        latency_sum += point_latency_sum
        latency_samples += point_latency_samples
        if point_max_latency is not None:
            max_latency_ms = max(max_latency_ms or 0, point_max_latency)
        points.append({
            "bucket_start": row[0],
            "agent_id": row[1],
            "country": row[2],
            "region": row[3],
            "checks": checks,
            "successful_checks": successes,
            "availability": round(successes * 100 / checks, 2) if checks else None,
            "latency_sum_ms": point_latency_sum,
            "latency_samples": point_latency_samples,
            "avg_latency_ms": (
                round(point_latency_sum / point_latency_samples)
                if point_latency_samples else None
            ),
            "max_latency_ms": point_max_latency,
        })

    return {
        "site_id": site_id,
        "url": url,
        "days": days,
        "granularity": granularity,
        "availability_policy": {
            "basis": "observed_agent_checks",
            "missing_checks": "excluded",
            "planned_maintenance": "excluded",
        },
        "summary": {
            "checks": total_checks,
            "availability": (
                round(successful_checks * 100 / total_checks, 2)
                if total_checks else None
            ),
            "avg_latency_ms": (
                round(latency_sum / latency_samples)
                if latency_samples else None
            ),
            "max_latency_ms": max_latency_ms,
            "events": len(events),
            "central_incidents": len(incidents),
            "central_downtime_seconds": central_downtime_seconds,
        },
        "points": points,
        "incidents": incidents,
        "events": events,
    }

def get_user_logs():
    since = datetime.utcnow() - timedelta(days=14)
    c.execute("SELECT created_at, user_id, username, action FROM user_logs WHERE created_at > %s ORDER BY created_at DESC", (since,))
    return c.fetchall()

def export_user_logs_csv():
    path = "/tmp/user_logs.csv"
    logs = get_user_logs()
    with open(path, "w", newline="") as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(["Дата", "Пользователь", "Username", "Действие"])
        for ts, user_id, username, action in logs:
            writer.writerow([ts, user_id, username or "", action])
    return path

def export_sites_csv():
    path = "/tmp/sites.csv"
    c.execute("SELECT user_id, username, url, last_status FROM sites")
    data = c.fetchall()
    with open(path, "w", newline="") as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(["Пользователь", "Username", "URL", "Статус"])
        for user_id, username, url, status in data:
            writer.writerow([user_id, username or "", url, status])
    return path

#Добавим функции для получения/обновления флагов
#def get_site_flags(url):
#    c.execute("SELECT notified_http, notified_ssl, notified_domain FROM sites WHERE url = %s", (url,))
#    row = c.fetchone()
#    return {"http": row[0], "ssl": row[1], "domain": row[2]} if row else {}

#def set_site_flags(url, http=None, ssl=None, domain=None):
#    updates = []
#    values = []
#
#    if http is not None:
#        updates.append("notified_http = %s")
#        values.append(http)
#    if ssl is not None:
#        updates.append("notified_ssl = %s")
#        values.append(ssl)
#    if domain is not None:
#        updates.append("notified_domain = %s")
#        values.append(domain)
#
#    if updates:
#        values.append(url)
#        query = f"UPDATE sites SET {', '.join(updates)} WHERE url = %s"
#        c.execute(query, tuple(values))
#        conn.commit()

def get_site_flags(url):
    c.execute("""
        SELECT notified_http, notified_http_ts,
               notified_ssl, notified_domain, 
               notified_ssl_ts, notified_domain_ts,
               domain_last_checked, domain_last_days,
               domain_last_registrar, domain_last_contact_url,
               http_fail_count
        FROM sites WHERE url = %s
    """, (url,))
    row = c.fetchone()
    if not row:
        return {}
    return {
        "http": bool(row[0]),
        "http_ts": row[1],
        "ssl": bool(row[2]),
        "domain": bool(row[3]),
        "ssl_ts": row[4],
        "domain_ts": row[5],
        "domain_check_ts": row[6],
        "domain_days_cache": row[7],
        "domain_registrar_cache": row[8],
        "domain_contact_url_cache": row[9],
        "http_fail_count": row[10] or 0,
    }

def get_site_flags_by_id(site_id):
    c.execute("""
        SELECT notified_http, notified_http_ts,
               notified_ssl, notified_domain,
               notified_ssl_ts, notified_domain_ts,
               domain_last_checked, domain_last_days,
               domain_last_registrar, domain_last_contact_url,
               http_fail_count
        FROM sites WHERE id = %s
    """, (site_id,))
    row = c.fetchone()
    if not row:
        return {}
    return {
        "http": bool(row[0]),
        "http_ts": row[1],
        "ssl": bool(row[2]),
        "domain": bool(row[3]),
        "ssl_ts": row[4],
        "domain_ts": row[5],
        "domain_check_ts": row[6],
        "domain_days_cache": row[7],
        "domain_registrar_cache": row[8],
        "domain_contact_url_cache": row[9],
        "http_fail_count": row[10] or 0,
    }

def set_site_flags(
    url,
    http=UNSET,
    http_ts=UNSET,
    ssl=UNSET,
    domain=UNSET,
    ssl_ts=UNSET,
    domain_ts=UNSET,
    domain_check_ts=UNSET,
    domain_days_cache=UNSET,
    domain_registrar_cache=UNSET,
    domain_contact_url_cache=UNSET,
    http_fail_count=UNSET,
):
    updates = []
    values = []

    if http is not UNSET:
        updates.append("notified_http = %s")
        values.append(http)
    if http_ts is not UNSET:
        updates.append("notified_http_ts = %s")
        values.append(http_ts)
    if ssl is not UNSET:
        updates.append("notified_ssl = %s")
        values.append(ssl)
    if domain is not UNSET:
        updates.append("notified_domain = %s")
        values.append(domain)
    if ssl_ts is not UNSET:
        updates.append("notified_ssl_ts = %s")
        values.append(ssl_ts)
    if domain_ts is not UNSET:
        updates.append("notified_domain_ts = %s")
        values.append(domain_ts)
    if domain_check_ts is not UNSET:
        updates.append("domain_last_checked = %s")
        values.append(domain_check_ts)
    if domain_days_cache is not UNSET:
        updates.append("domain_last_days = %s")
        values.append(domain_days_cache)
    if domain_registrar_cache is not UNSET:
        updates.append("domain_last_registrar = %s")
        values.append(domain_registrar_cache)
    if domain_contact_url_cache is not UNSET:
        updates.append("domain_last_contact_url = %s")
        values.append(domain_contact_url_cache)
    if http_fail_count is not UNSET:
        updates.append("http_fail_count = %s")
        values.append(http_fail_count)

    if not updates:
        return

    values.append(url)
    query = f"UPDATE sites SET {', '.join(updates)} WHERE url = %s"
    c.execute(query, tuple(values))
    conn.commit()

def set_site_flags_by_id(
    site_id,
    http=UNSET,
    http_ts=UNSET,
    ssl=UNSET,
    domain=UNSET,
    ssl_ts=UNSET,
    domain_ts=UNSET,
    domain_check_ts=UNSET,
    domain_days_cache=UNSET,
    domain_registrar_cache=UNSET,
    domain_contact_url_cache=UNSET,
    http_fail_count=UNSET,
):
    updates = []
    values = []

    if http is not UNSET:
        updates.append("notified_http = %s")
        values.append(http)
    if http_ts is not UNSET:
        updates.append("notified_http_ts = %s")
        values.append(http_ts)
    if ssl is not UNSET:
        updates.append("notified_ssl = %s")
        values.append(ssl)
    if domain is not UNSET:
        updates.append("notified_domain = %s")
        values.append(domain)
    if ssl_ts is not UNSET:
        updates.append("notified_ssl_ts = %s")
        values.append(ssl_ts)
    if domain_ts is not UNSET:
        updates.append("notified_domain_ts = %s")
        values.append(domain_ts)
    if domain_check_ts is not UNSET:
        updates.append("domain_last_checked = %s")
        values.append(domain_check_ts)
    if domain_days_cache is not UNSET:
        updates.append("domain_last_days = %s")
        values.append(domain_days_cache)
    if domain_registrar_cache is not UNSET:
        updates.append("domain_last_registrar = %s")
        values.append(domain_registrar_cache)
    if domain_contact_url_cache is not UNSET:
        updates.append("domain_last_contact_url = %s")
        values.append(domain_contact_url_cache)
    if http_fail_count is not UNSET:
        updates.append("http_fail_count = %s")
        values.append(http_fail_count)

    if not updates:
        return

    values.append(site_id)
    query = f"UPDATE sites SET {', '.join(updates)} WHERE id = %s"
    c.execute(query, tuple(values))
    conn.commit()


#def migrate_add_notification_flags():
#    c.execute("""
#        DO $$
#        BEGIN
#            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
#                           WHERE table_name='sites' AND column_name='notified_http') THEN
#                ALTER TABLE sites ADD COLUMN notified_http BOOLEAN DEFAULT FALSE;
#            END IF;
#
#            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
#                           WHERE table_name='sites' AND column_name='notified_ssl') THEN
#                ALTER TABLE sites ADD COLUMN notified_ssl BOOLEAN DEFAULT FALSE;
#            END IF;
#
#            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
#                           WHERE table_name='sites' AND column_name='notified_domain') THEN
#                ALTER TABLE sites ADD COLUMN notified_domain BOOLEAN DEFAULT FALSE;
#            END IF;
#        END$$;
#    """)
def migrate_add_notification_flags():
    c.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                           WHERE table_name='sites' AND column_name='notified_http') THEN
                ALTER TABLE sites ADD COLUMN notified_http BOOLEAN DEFAULT FALSE;
            END IF;

            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                           WHERE table_name='sites' AND column_name='notified_http_ts') THEN
                ALTER TABLE sites ADD COLUMN notified_http_ts TIMESTAMP;
            END IF;

            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                           WHERE table_name='sites' AND column_name='notified_ssl') THEN
                ALTER TABLE sites ADD COLUMN notified_ssl BOOLEAN DEFAULT FALSE;
            END IF;

            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                           WHERE table_name='sites' AND column_name='notified_domain') THEN
                ALTER TABLE sites ADD COLUMN notified_domain BOOLEAN DEFAULT FALSE;
            END IF;

            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                           WHERE table_name='sites' AND column_name='notified_ssl_ts') THEN
                ALTER TABLE sites ADD COLUMN notified_ssl_ts TIMESTAMP;
            END IF;

            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                           WHERE table_name='sites' AND column_name='notified_domain_ts') THEN
                ALTER TABLE sites ADD COLUMN notified_domain_ts TIMESTAMP;
            END IF;

            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                           WHERE table_name='sites' AND column_name='domain_last_checked') THEN
                ALTER TABLE sites ADD COLUMN domain_last_checked TIMESTAMP;
            END IF;

            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                           WHERE table_name='sites' AND column_name='domain_last_days') THEN
                ALTER TABLE sites ADD COLUMN domain_last_days INTEGER;
            END IF;

            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                           WHERE table_name='sites' AND column_name='domain_last_registrar') THEN
                ALTER TABLE sites ADD COLUMN domain_last_registrar TEXT;
            END IF;

            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                           WHERE table_name='sites' AND column_name='domain_last_contact_url') THEN
                ALTER TABLE sites ADD COLUMN domain_last_contact_url TEXT;
            END IF;

            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                           WHERE table_name='sites' AND column_name='http_fail_count') THEN
                ALTER TABLE sites ADD COLUMN http_fail_count INTEGER DEFAULT 0;
            END IF;

            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                           WHERE table_name='sites' AND column_name='is_paused') THEN
                ALTER TABLE sites ADD COLUMN is_paused BOOLEAN DEFAULT FALSE;
            END IF;

            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                           WHERE table_name='sites' AND column_name='paused_until') THEN
                ALTER TABLE sites ADD COLUMN paused_until TIMESTAMP;
            END IF;

            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                           WHERE table_name='sites' AND column_name='incident_started_at') THEN
                ALTER TABLE sites ADD COLUMN incident_started_at TIMESTAMP;
            END IF;

            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                           WHERE table_name='sites' AND column_name='last_success_at') THEN
                ALTER TABLE sites ADD COLUMN last_success_at TIMESTAMP;
            END IF;

            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                           WHERE table_name='sites' AND column_name='last_success_http_status') THEN
                ALTER TABLE sites ADD COLUMN last_success_http_status INTEGER;
            END IF;

            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                           WHERE table_name='sites' AND column_name='last_success_latency_ms') THEN
                ALTER TABLE sites ADD COLUMN last_success_latency_ms INTEGER;
            END IF;

            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                           WHERE table_name='sites' AND column_name='last_resolved_ip') THEN
                ALTER TABLE sites ADD COLUMN last_resolved_ip TEXT;
            END IF;

            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                           WHERE table_name='sites' AND column_name='site_group') THEN
                ALTER TABLE sites ADD COLUMN site_group TEXT DEFAULT '';
            END IF;
        END
        $$;
    """)
    c.execute("CREATE INDEX IF NOT EXISTS idx_sites_user_id ON sites(user_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_sites_url ON sites(url)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_events_created_at ON events(created_at)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_user_logs_created_at ON user_logs(created_at)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_bot_messages_created_at ON bot_messages(created_at)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_bot_messages_user_id ON bot_messages(user_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_agent_check_results_url_created_at ON agent_check_results(url, created_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_agent_check_results_agent_id ON agent_check_results(agent_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_agent_check_hourly_url_bucket ON agent_check_hourly(url, bucket_start DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_agent_check_hourly_bucket_start ON agent_check_hourly(bucket_start)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_agent_check_daily_url_bucket ON agent_check_daily(url, bucket_start DESC)")
    c.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_central_incidents_active_site ON central_incidents(site_id) WHERE ended_at IS NULL")
    c.execute("CREATE INDEX IF NOT EXISTS idx_central_incidents_site_started ON central_incidents(site_id, started_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_central_incidents_url_started ON central_incidents(url, started_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_events_url_created_at ON events(url, created_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_sites_user_group ON sites(user_id, site_group)")
    c.execute("ALTER TABLE feedback_conversations ADD COLUMN IF NOT EXISTS active_media_group_id TEXT")
    c.execute("ALTER TABLE feedback_messages ADD COLUMN IF NOT EXISTS telegram_message_id BIGINT")
    c.execute("ALTER TABLE feedback_messages ADD COLUMN IF NOT EXISTS media_type TEXT")
    c.execute("ALTER TABLE feedback_messages ADD COLUMN IF NOT EXISTS telegram_file_id TEXT")
    c.execute("ALTER TABLE feedback_messages ADD COLUMN IF NOT EXISTS telegram_file_unique_id TEXT")
    c.execute("ALTER TABLE feedback_messages ADD COLUMN IF NOT EXISTS file_name TEXT")
    c.execute("ALTER TABLE feedback_messages ADD COLUMN IF NOT EXISTS mime_type TEXT")
    c.execute("ALTER TABLE feedback_messages ADD COLUMN IF NOT EXISTS file_size BIGINT")
    c.execute("ALTER TABLE feedback_messages ADD COLUMN IF NOT EXISTS media_group_id TEXT")
    c.execute("CREATE INDEX IF NOT EXISTS idx_feedback_conversations_last_message ON feedback_conversations(last_message_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_feedback_messages_conversation_created ON feedback_messages(conversation_id, created_at)")

    conn.commit()
