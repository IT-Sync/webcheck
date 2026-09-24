"""Additive base PostgreSQL schema setup."""


def ensure_base_schema(cursor, connection):
    cursor.execute('''CREATE TABLE IF NOT EXISTS sites (
        id SERIAL PRIMARY KEY,
        user_id BIGINT,
        username TEXT,
        url TEXT,
        last_status TEXT,
        last_checked TIMESTAMP
    )''')

    cursor.execute('''CREATE TABLE IF NOT EXISTS projects (
        id BIGSERIAL PRIMARY KEY,
        owner_user_id BIGINT NOT NULL,
        name TEXT NOT NULL,
        is_personal BOOLEAN NOT NULL DEFAULT FALSE,
        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
    )''')

    cursor.execute('''CREATE TABLE IF NOT EXISTS project_members (
        project_id BIGINT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
        user_id BIGINT NOT NULL,
        role TEXT NOT NULL CHECK (role IN ('viewer', 'manager')),
        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (project_id, user_id)
    )''')

    cursor.execute('''CREATE TABLE IF NOT EXISTS events (
        id SERIAL PRIMARY KEY,
        url TEXT,
        message TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')

    cursor.execute('''CREATE TABLE IF NOT EXISTS user_logs (
        id SERIAL PRIMARY KEY,
        user_id BIGINT,
        username TEXT,
        action TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')

    cursor.execute('''CREATE TABLE IF NOT EXISTS bot_messages (
        id SERIAL PRIMARY KEY,
        user_id BIGINT,
        source TEXT,
        status TEXT,
        error TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')

    cursor.execute('''CREATE TABLE IF NOT EXISTS agent_check_results (
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

    cursor.execute('''CREATE TABLE IF NOT EXISTS agent_check_hourly (
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

    cursor.execute('''CREATE TABLE IF NOT EXISTS agent_check_daily (
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

    cursor.execute('''CREATE TABLE IF NOT EXISTS central_incidents (
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

    cursor.execute('''CREATE TABLE IF NOT EXISTS site_tags (
        site_id INTEGER NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
        tag TEXT NOT NULL,
        PRIMARY KEY (site_id, tag)
    )''')

    cursor.execute('''CREATE TABLE IF NOT EXISTS maintenance_windows (
        id BIGSERIAL PRIMARY KEY,
        site_id INTEGER NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
        starts_at TIMESTAMP NOT NULL,
        ends_at TIMESTAMP NOT NULL,
        reason TEXT NOT NULL DEFAULT '',
        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        cancelled_at TIMESTAMP,
        CHECK (ends_at > starts_at)
    )''')

    cursor.execute('''CREATE TABLE IF NOT EXISTS feedback_conversations (
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

    cursor.execute('''CREATE TABLE IF NOT EXISTS feedback_messages (
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

    connection.commit()
