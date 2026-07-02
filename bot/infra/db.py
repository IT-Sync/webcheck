import psycopg2
import os
from datetime import datetime, timedelta
import csv

UNSET = object()

conn = psycopg2.connect(
    dbname=os.getenv("DB_NAME", "devcheck"),
    user=os.getenv("DB_USER", "user"),
    password=os.getenv("DB_PASS", "password"),
    host=os.getenv("DB_HOST", "localhost"),
    port=os.getenv("DB_PORT", "5432")
)
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

conn.commit()

# Методы
def add_site(user_id, url, username=None):
    c.execute("INSERT INTO sites (user_id, username, url) VALUES (%s, %s, %s) RETURNING id", (user_id, username, url))
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
               (COALESCE(is_paused, FALSE) OR (paused_until IS NOT NULL AND paused_until > %s)) AS is_paused_now
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
    conn.commit()
    return sites_deleted, logs_deleted, messages_deleted

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
               (COALESCE(is_paused, FALSE) OR (paused_until IS NOT NULL AND paused_until > %s)) AS is_paused_now
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
               (COALESCE(is_paused, FALSE) OR (paused_until IS NOT NULL AND paused_until > %s)) AS is_paused_now
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

def start_site_incident(site_id, started_at, resolved_ip=None):
    c.execute(
        """
        UPDATE sites
        SET incident_started_at = COALESCE(incident_started_at, %s),
            last_resolved_ip = COALESCE(%s, last_resolved_ip)
        WHERE id = %s
        RETURNING incident_started_at
        """,
        (started_at, resolved_ip, site_id)
    )
    row = c.fetchone()
    conn.commit()
    return row[0] if row else started_at

def clear_site_incident(site_id):
    c.execute("UPDATE sites SET incident_started_at = NULL WHERE id = %s", (site_id,))
    conn.commit()

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
        END
        $$;
    """)
    c.execute("CREATE INDEX IF NOT EXISTS idx_sites_user_id ON sites(user_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_sites_url ON sites(url)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_events_created_at ON events(created_at)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_user_logs_created_at ON user_logs(created_at)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_bot_messages_created_at ON bot_messages(created_at)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_bot_messages_user_id ON bot_messages(user_id)")

    conn.commit()
