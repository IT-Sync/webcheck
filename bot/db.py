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

conn.commit()

# Методы
def add_site(user_id, url, username=None):
    c.execute("INSERT INTO sites (user_id, username, url) VALUES (%s, %s, %s)", (user_id, username, url))
    conn.commit()

def get_sites(user_id):
    c.execute("SELECT * FROM sites WHERE user_id = %s", (user_id,))
    return c.fetchall()

def delete_site(user_id, url):
    c.execute("DELETE FROM sites WHERE user_id = %s AND url = %s", (user_id, url))
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
    conn.commit()
    return sites_deleted, logs_deleted

def get_all_sites(full=False):
    if full:
        c.execute("SELECT user_id, url, username FROM sites")
    else:
        c.execute("SELECT DISTINCT user_id, url FROM sites")
    return c.fetchall()

def update_site_status(url, status):
    c.execute("UPDATE sites SET last_status = %s, last_checked = %s WHERE url = %s", (status, datetime.utcnow(), url))
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

#def admin_delete_site(url):
#    c.execute("DELETE FROM sites WHERE url = %s", (url,))
#    conn.commit()

def admin_delete_site(user_id, url):
    c.execute("DELETE FROM sites WHERE user_id = %s AND url = %s", (user_id, url))
    conn.commit()


def log_user_action(user_id, action, username=None):
    c.execute("INSERT INTO user_logs (user_id, username, action) VALUES (%s, %s, %s)", (user_id, username, action))
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
        SELECT notified_http, notified_ssl, notified_domain, 
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
        "ssl": bool(row[1]),
        "domain": bool(row[2]),
        "ssl_ts": row[3],
        "domain_ts": row[4],
        "domain_check_ts": row[5],
        "domain_days_cache": row[6],
        "domain_registrar_cache": row[7],
        "domain_contact_url_cache": row[8],
        "http_fail_count": row[9] or 0,
    }

def set_site_flags(
    url,
    http=UNSET,
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
        END
        $$;
    """)

    conn.commit()
