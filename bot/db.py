import psycopg2
import os
from datetime import datetime, timedelta
import csv

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
               notified_ssl_ts, notified_domain_ts
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
    }

def set_site_flags(url, http=None, ssl=None, domain=None, ssl_ts=None, domain_ts=None):
    if http is not None:
        c.execute("UPDATE sites SET notified_http = %s WHERE url = %s", (http, url))
    if ssl is not None:
        c.execute("UPDATE sites SET notified_ssl = %s WHERE url = %s", (ssl, url))
    if domain is not None:
        c.execute("UPDATE sites SET notified_domain = %s WHERE url = %s", (domain, url))
    if ssl_ts is not None:
        c.execute("UPDATE sites SET notified_ssl_ts = %s WHERE url = %s", (ssl_ts, url))
    if domain_ts is not None:
        c.execute("UPDATE sites SET notified_domain_ts = %s WHERE url = %s", (domain_ts, url))
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
        END
        $$;
    """)

    conn.commit()

