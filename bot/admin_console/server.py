import asyncio
import html
import os
from datetime import datetime
from urllib.parse import urlencode

from aiohttp import web
from aiogram.exceptions import TelegramForbiddenError

from bot.infra.db import (
    admin_delete_site_by_id,
    delete_user_data,
    get_admin_bot_response_stats,
    get_admin_command_stats,
    get_admin_message_stats,
    get_admin_sites,
    get_admin_stats,
    get_admin_usage_stats,
    get_admin_user,
    get_admin_users,
    get_event_logs,
    get_site_by_id,
    get_user_logs,
    log_user_action,
    set_site_paused_by_id,
)


ADMIN_WEB_TOKEN = os.getenv("ADMIN_WEB_TOKEN")
ADMIN_WEB_HOST = os.getenv("ADMIN_WEB_HOST", "0.0.0.0")
ADMIN_WEB_PORT = int(os.getenv("ADMIN_WEB_PORT", "8080"))
BOT_OWNER_ID = int(os.getenv("BOT_OWNER_ID", "0"))


def esc(value) -> str:
    if value is None:
        return ""
    return html.escape(str(value), quote=True)


def fmt_dt(value) -> str:
    if not value:
        return "нет данных"
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M")
    return esc(value)


def redirect_messages(result: str) -> web.HTTPFound:
    return web.HTTPFound("/admin/messages?" + urlencode({"result": result}))


def bar_chart(rows, value_key: str, label: str, empty_text: str = "Данных пока нет") -> str:
    max_value = max((row.get(value_key, 0) for row in rows), default=0)
    if max_value <= 0:
        return f'<div class="panel muted">{empty_text}</div>'
    bars = []
    for row in rows:
        value = row.get(value_key, 0)
        height = max(4, int((value / max_value) * 120)) if value else 4
        date_label = row["date"].strftime("%d.%m")
        bars.append(
            f"""<div class="bar-item" title="{esc(date_label)}: {value}">
  <div class="bar-value">{value}</div>
  <div class="bar" style="height:{height}px"></div>
  <div class="bar-label">{esc(date_label)}</div>
</div>"""
        )
    return f'<div class="chart" aria-label="{esc(label)}">{"".join(bars)}</div>'


def is_authenticated(request: web.Request) -> bool:
    token = request.cookies.get("admin_token") or request.query.get("token")
    return bool(ADMIN_WEB_TOKEN and token == ADMIN_WEB_TOKEN)


def require_auth(handler):
    async def wrapped(request):
        if not is_authenticated(request):
            raise web.HTTPFound("/admin/login")
        return await handler(request)

    return wrapped


def page(title: str, body: str, active: str = "") -> web.Response:
    nav = [
        ("dashboard", "/admin/", "Обзор"),
        ("users", "/admin/users", "Пользователи"),
        ("logs", "/admin/logs", "Логи"),
        ("events", "/admin/events", "События"),
        ("messages", "/admin/messages", "Сообщения"),
    ]
    nav_html = "".join(
        f'<a class="{ "active" if key == active else "" }" href="{href}">{label}</a>'
        for key, href, label in nav
    )
    html_text = f"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{esc(title)} · Webcheck Admin</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f6f7f9;
      --panel: #ffffff;
      --text: #1f2933;
      --muted: #65727f;
      --line: #d9dee5;
      --accent: #176b87;
      --danger: #b42318;
      --ok: #16794c;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font: 14px/1.45 system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}
    header {{
      background: #263238;
      color: #fff;
      padding: 14px 24px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
    }}
    header h1 {{ margin: 0; font-size: 18px; font-weight: 650; }}
    nav {{
      display: flex;
      gap: 4px;
      overflow-x: auto;
      padding: 10px 24px;
      background: #e9edf2;
      border-bottom: 1px solid var(--line);
    }}
    nav a {{
      color: #24323d;
      text-decoration: none;
      padding: 8px 12px;
      border-radius: 6px;
      white-space: nowrap;
    }}
    nav a.active, nav a:hover {{ background: #fff; }}
    main {{ max-width: 1180px; margin: 0 auto; padding: 24px; }}
    h2 {{ margin: 0 0 16px; font-size: 22px; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 12px; margin-bottom: 24px; }}
    .metric, .panel {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 16px;
    }}
    .metric strong {{ display: block; font-size: 26px; line-height: 1.1; }}
    .metric span, .muted {{ color: var(--muted); }}
    table {{ width: 100%; border-collapse: collapse; background: var(--panel); border: 1px solid var(--line); }}
    th, td {{ padding: 10px 12px; border-bottom: 1px solid var(--line); text-align: left; vertical-align: top; }}
    th {{ background: #eef2f5; font-size: 12px; text-transform: uppercase; color: #52616e; }}
    tr:last-child td {{ border-bottom: 0; }}
    code {{ background: #eef2f5; padding: 2px 5px; border-radius: 4px; }}
    form.inline {{ display: inline; }}
    input, textarea, select {{
      width: 100%;
      border: 1px solid #b8c2cc;
      border-radius: 6px;
      padding: 9px 10px;
      font: inherit;
      background: #fff;
    }}
    textarea {{ min-height: 140px; resize: vertical; }}
    label {{ display: block; margin: 0 0 12px; color: #34414d; }}
    button, .button {{
      border: 0;
      border-radius: 6px;
      padding: 9px 12px;
      background: var(--accent);
      color: #fff;
      font: inherit;
      cursor: pointer;
      text-decoration: none;
      display: inline-block;
    }}
    button.secondary {{ background: #52616e; }}
    button.danger {{ background: var(--danger); }}
    .actions {{ display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }}
    .status-ok {{ color: var(--ok); font-weight: 650; }}
    .status-bad {{ color: var(--danger); font-weight: 650; }}
    .flash {{ margin-bottom: 16px; padding: 12px 14px; background: #e8f4f8; border: 1px solid #b7d8e3; border-radius: 8px; }}
    .split {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 16px; }}
    .chart {{
      min-height: 190px;
      display: flex;
      align-items: end;
      gap: 8px;
      padding: 14px 10px 8px;
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      overflow-x: auto;
    }}
    .bar-item {{ min-width: 44px; display: grid; gap: 5px; justify-items: center; align-items: end; }}
    .bar {{
      width: 28px;
      border-radius: 5px 5px 0 0;
      background: var(--accent);
    }}
    .bar-value {{ font-size: 12px; color: #34414d; }}
    .bar-label {{ font-size: 11px; color: var(--muted); white-space: nowrap; }}
    .user-head {{ display: flex; justify-content: space-between; align-items: start; gap: 16px; margin-bottom: 16px; }}
    .user-head h2 {{ margin-bottom: 4px; }}
    .subline {{ color: var(--muted); }}
    @media (max-width: 720px) {{
      header, nav {{ padding-left: 14px; padding-right: 14px; }}
      main {{ padding: 16px 12px; }}
      th, td {{ padding: 8px; }}
      .hide-sm {{ display: none; }}
    }}
  </style>
</head>
<body>
  <header><h1>Webcheck Admin</h1><a class="button" href="/admin/logout">Выйти</a></header>
  <nav>{nav_html}</nav>
  <main>{body}</main>
</body>
</html>"""
    return web.Response(text=html_text, content_type="text/html")


async def login_page(request: web.Request) -> web.Response:
    error = request.query.get("error")
    error_html = '<div class="flash">Неверный токен доступа.</div>' if error else ""
    return web.Response(
        text=f"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Вход · Webcheck Admin</title>
  <style>
    body {{ margin: 0; min-height: 100vh; display: grid; place-items: center; background: #f6f7f9; color: #1f2933; font: 14px system-ui, sans-serif; }}
    main {{ width: min(420px, calc(100vw - 32px)); background: #fff; border: 1px solid #d9dee5; border-radius: 8px; padding: 24px; }}
    h1 {{ margin: 0 0 18px; font-size: 22px; }}
    label {{ display: block; margin-bottom: 14px; }}
    input {{ width: 100%; border: 1px solid #b8c2cc; border-radius: 6px; padding: 10px; font: inherit; }}
    button {{ width: 100%; border: 0; border-radius: 6px; padding: 10px; background: #176b87; color: #fff; font: inherit; cursor: pointer; }}
    .flash {{ margin-bottom: 14px; padding: 10px; background: #fdecec; border: 1px solid #f3b7b7; border-radius: 6px; }}
  </style>
</head>
<body>
  <main>
    <h1>Webcheck Admin</h1>
    {error_html}
    <form method="post" action="/admin/login">
      <label>Токен администратора<input name="token" type="password" autocomplete="current-password" autofocus></label>
      <button type="submit">Войти</button>
    </form>
  </main>
</body>
</html>""",
        content_type="text/html",
    )


async def login(request: web.Request) -> web.Response:
    data = await request.post()
    if data.get("token") != ADMIN_WEB_TOKEN:
        raise web.HTTPFound("/admin/login?error=1")
    response = web.HTTPFound("/admin/")
    response.set_cookie("admin_token", ADMIN_WEB_TOKEN, httponly=True, samesite="Strict")
    return response


async def logout(request: web.Request) -> web.Response:
    response = web.HTTPFound("/admin/login")
    response.del_cookie("admin_token")
    return response


async def admin_root(request: web.Request) -> web.Response:
    raise web.HTTPFound("/admin/")


@require_auth
async def dashboard(request: web.Request) -> web.Response:
    stats = get_admin_stats()
    usage_stats = get_admin_usage_stats()
    message_stats = get_admin_message_stats()
    command_stats = get_admin_command_stats()
    response_stats = get_admin_bot_response_stats()
    recent_logs = get_user_logs()[:10]
    recent_events = get_event_logs()[:10]
    metrics = [
        ("Пользователей с сайтами", stats["users_with_sites"]),
        ("Сайтов", stats["site_count"]),
        ("Активных сайтов", stats["active_sites"]),
        ("На паузе", stats["paused_sites"]),
        ("Активных за 14 дней", stats["active_users_14d"]),
        ("Логов за 14 дней", stats["logs_14d"]),
        ("Событий за 14 дней", stats["events_14d"]),
        ("Сообщений бота", stats["sent_messages_14d"]),
        ("Ошибок отправки", stats["failed_messages_14d"]),
    ]
    metric_html = "".join(f'<div class="metric"><strong>{value}</strong><span>{label}</span></div>' for label, value in metrics)
    logs_html = "".join(
        f"<tr><td>{fmt_dt(ts)}</td><td>{esc(user_id)}</td><td>{esc(username or 'без username')}</td><td>{esc(action)}</td></tr>"
        for ts, user_id, username, action in recent_logs
    ) or '<tr><td colspan="4">Логов нет</td></tr>'
    events_html = "".join(
        f"<tr><td>{fmt_dt(ts)}</td><td>{esc(url)}</td><td>{esc(message)}</td></tr>"
        for ts, url, message in recent_events
    ) or '<tr><td colspan="3">Событий нет</td></tr>'
    commands_html = "".join(
        f"<tr><td><code>{esc(row['command'])}</code></td><td>{row['total']}</td><td>{row['users']}</td></tr>"
        for row in command_stats
    ) or '<tr><td colspan="3">Команд пока нет</td></tr>'
    responses_html = "".join(
        f"<tr><td>{esc(row['source'])}</td><td>{row['sent']}</td><td>{row['failed']}</td></tr>"
        for row in response_stats
    ) or '<tr><td colspan="3">Ответов пока нет</td></tr>'
    body = f"""
<h2>Обзор</h2>
<div class="grid">{metric_html}</div>
<div class="split" style="margin-bottom:24px">
  <section>
    <h2>Действия пользователей</h2>
    {bar_chart(usage_stats, "actions", "Действия пользователей")}
  </section>
  <section>
    <h2>Сообщения бота</h2>
    {bar_chart(message_stats, "sent", "Отправленные сообщения", "Отправленных сообщений пока нет")}
  </section>
</div>
<div class="split" style="margin-bottom:24px">
  <section>
    <h2>Популярные команды</h2>
    <table><thead><tr><th>Команда</th><th>Вызовов</th><th>Пользователей</th></tr></thead><tbody>{commands_html}</tbody></table>
  </section>
  <section>
    <h2>Ответы бота</h2>
    <table><thead><tr><th>Тип</th><th>Отправлено</th><th>Ошибок</th></tr></thead><tbody>{responses_html}</tbody></table>
  </section>
</div>
<div class="split">
  <section>
    <h2>Последние логи</h2>
    <table><thead><tr><th>Дата</th><th>User ID</th><th>Username</th><th>Действие</th></tr></thead><tbody>{logs_html}</tbody></table>
  </section>
  <section>
    <h2>Последние события</h2>
    <table><thead><tr><th>Дата</th><th>URL</th><th>Событие</th></tr></thead><tbody>{events_html}</tbody></table>
  </section>
</div>"""
    return page("Обзор", body, "dashboard")


@require_auth
async def users(request: web.Request) -> web.Response:
    rows = get_admin_users()
    table = "".join(
        f"""<tr>
  <td><a href="/admin/users/{row['user_id']}"><code>{row['user_id']}</code></a></td>
  <td>{esc('@' + row['username'] if row['username'] else 'без username')}</td>
  <td>{row['site_count']}</td>
  <td>{fmt_dt(row['last_action_at'])}</td>
  <td><a class="button" href="/admin/messages?user_id={row['user_id']}">Сообщение</a></td>
</tr>"""
        for row in rows
    ) or '<tr><td colspan="5">Пользователей нет</td></tr>'
    body = f"""
<h2>Пользователи</h2>
<table>
  <thead><tr><th>User ID</th><th>Username</th><th>Сайтов</th><th>Последнее действие</th><th></th></tr></thead>
  <tbody>{table}</tbody>
</table>"""
    return page("Пользователи", body, "users")


@require_auth
async def user_detail(request: web.Request) -> web.Response:
    user_id = int(request.match_info["user_id"])
    profile = get_admin_user(user_id)
    sites = get_admin_sites(user_id=user_id)
    logs = [row for row in get_user_logs() if row[1] == user_id][:30]
    username = profile.get("username")
    title = f"@{username}" if username else "без username"
    site_rows = "".join(
        f"""<tr>
  <td>{esc(site['url'])}</td>
  <td>{'<span class="status-bad">пауза</span>' if site['is_paused'] else '<span class="status-ok">активен</span>'}</td>
  <td>{fmt_dt(site['last_checked'])}</td>
  <td>{esc((site['last_status'] or 'нет данных')[:240])}</td>
  <td class="actions">
    <form class="inline" method="post" action="/admin/sites/{site['id']}/{'resume' if site['is_paused'] else 'pause'}"><button class="secondary" type="submit">{'Возобновить' if site['is_paused'] else 'Пауза'}</button></form>
    <form class="inline" method="post" action="/admin/sites/{site['id']}/delete"><button class="danger" type="submit">Удалить</button></form>
  </td>
</tr>"""
        for site in sites
    ) or '<tr><td colspan="5">Сайтов нет</td></tr>'
    log_rows = "".join(
        f"<tr><td>{fmt_dt(ts)}</td><td>{esc(username or 'без username')}</td><td>{esc(action)}</td></tr>"
        for ts, _, username, action in logs
    ) or '<tr><td colspan="3">Логов нет</td></tr>'
    body = f"""
<div class="user-head">
  <div>
    <h2>{esc(title)}</h2>
    <div class="subline">User ID: <code>{user_id}</code> · сайтов: {profile.get("site_count", 0)} · последнее действие: {fmt_dt(profile.get("last_action_at"))}</div>
  </div>
  <div class="actions">
    <a class="button" href="/admin/messages?user_id={user_id}">Отправить сообщение</a>
    <form class="inline" method="post" action="/admin/users/{user_id}/delete"><button class="danger" type="submit">Удалить данные пользователя</button></form>
  </div>
</div>
<h2>Сайты</h2>
<table><thead><tr><th>URL</th><th>Статус</th><th>Проверка</th><th>Последний результат</th><th></th></tr></thead><tbody>{site_rows}</tbody></table>
<h2 style="margin-top:24px">Логи пользователя</h2>
<table><thead><tr><th>Дата</th><th>Username</th><th>Действие</th></tr></thead><tbody>{log_rows}</tbody></table>"""
    return page(f"Пользователь {user_id}", body, "users")


@require_auth
async def logs(request: web.Request) -> web.Response:
    rows = get_user_logs()
    table = "".join(
        f"<tr><td>{fmt_dt(ts)}</td><td><a href=\"/admin/users/{user_id}\"><code>{user_id}</code></a></td><td>{esc(username or 'без username')}</td><td>{esc(action)}</td></tr>"
        for ts, user_id, username, action in rows
    ) or '<tr><td colspan="4">Логов нет</td></tr>'
    body = f"""
<h2>Логи действий за 14 дней</h2>
<table><thead><tr><th>Дата</th><th>User ID</th><th>Username</th><th>Действие</th></tr></thead><tbody>{table}</tbody></table>"""
    return page("Логи", body, "logs")


@require_auth
async def events(request: web.Request) -> web.Response:
    rows = get_event_logs()
    table = "".join(
        f"<tr><td>{fmt_dt(ts)}</td><td>{esc(url)}</td><td>{esc(message)}</td></tr>"
        for ts, url, message in rows
    ) or '<tr><td colspan="3">Событий нет</td></tr>'
    body = f"""
<h2>События мониторинга за 14 дней</h2>
<table><thead><tr><th>Дата</th><th>URL</th><th>Событие</th></tr></thead><tbody>{table}</tbody></table>"""
    return page("События", body, "events")


@require_auth
async def messages(request: web.Request) -> web.Response:
    user_id = request.query.get("user_id", "")
    username = ""
    recipient_html = ""
    recipient_fields = '<label>User ID<input name="user_id" value="" inputmode="numeric" required></label>'
    if user_id.isdigit():
        profile = get_admin_user(int(user_id))
        username = profile.get("username") or ""
        recipient_name = f"@{username}" if username else "без username"
        recipient_html = (
            f'<div class="flash">Получатель: <strong>{esc(recipient_name)}</strong> '
            f'· User ID: <code>{esc(user_id)}</code></div>'
        )
        recipient_fields = f'<input type="hidden" name="user_id" value="{esc(user_id)}">'
    flash = esc(request.query.get("result", ""))
    flash_html = f'<div class="flash">{flash}</div>' if flash else ""
    body = f"""
<h2>Сообщения от имени бота</h2>
{flash_html}
<div class="split">
  <section class="panel">
    <h2>Одному пользователю</h2>
    {recipient_html}
    <form method="post" action="/admin/messages/send">
      {recipient_fields}
      <label>Сообщение<textarea name="text" required></textarea></label>
      <button type="submit">Отправить</button>
    </form>
  </section>
  <section class="panel">
    <h2>Всем пользователям</h2>
    <form method="post" action="/admin/messages/broadcast">
      <label>Сообщение<textarea name="text" required></textarea></label>
      <label><input style="width:auto;margin-right:8px" type="checkbox" name="confirm" value="1" required>Подтверждаю массовую отправку</label>
      <button class="danger" type="submit">Отправить всем</button>
    </form>
  </section>
</div>"""
    return page("Сообщения", body, "messages")


@require_auth
async def send_message(request: web.Request) -> web.Response:
    data = await request.post()
    user_id = int(data["user_id"])
    text = str(data["text"]).strip()
    if not text:
        raise redirect_messages("Сообщение пустое")
    bot = request.app["bot"]
    try:
        await bot.send_message(user_id, text)
    except TelegramForbiddenError:
        raise redirect_messages("Пользователь заблокировал бота")
    except Exception as e:
        raise redirect_messages(f"Ошибка отправки: {type(e).__name__}")
    log_user_action(BOT_OWNER_ID, f"web: отправил сообщение пользователю {user_id}", "web-admin")
    raise redirect_messages("Сообщение отправлено")


@require_auth
async def broadcast_message(request: web.Request) -> web.Response:
    data = await request.post()
    text = str(data["text"]).strip()
    if not text:
        raise redirect_messages("Сообщение пустое")
    if data.get("confirm") != "1":
        raise redirect_messages("Массовая отправка не подтверждена")
    bot = request.app["bot"]
    users = get_admin_users()
    sent = 0
    failed = 0
    for user in users:
        try:
            await bot.send_message(user["user_id"], text)
            sent += 1
            await asyncio.sleep(0.04)
        except TelegramForbiddenError:
            failed += 1
        except Exception as e:
            failed += 1
    log_user_action(BOT_OWNER_ID, f"web: массовая отправка, успешно {sent}, ошибок {failed}", "web-admin")
    raise redirect_messages(f"Массовая отправка завершена: успешно {sent}, ошибок {failed}")


@require_auth
async def delete_user(request: web.Request) -> web.Response:
    user_id = int(request.match_info["user_id"])
    sites_deleted, logs_deleted, messages_deleted = delete_user_data(user_id)
    log_user_action(
        BOT_OWNER_ID,
        f"web: удалил пользователя {user_id}, сайтов {sites_deleted}, логов {logs_deleted}, сообщений {messages_deleted}",
        "web-admin"
    )
    raise web.HTTPFound("/admin/users")


@require_auth
async def delete_site(request: web.Request) -> web.Response:
    site_id = int(request.match_info["site_id"])
    site = get_site_by_id(site_id)
    admin_delete_site_by_id(site_id)
    if site:
        log_user_action(BOT_OWNER_ID, f"web: удалил сайт {site[3]} пользователя {site[1]}", "web-admin")
        raise web.HTTPFound(f"/admin/users/{site[1]}")
    raise web.HTTPFound("/admin/users")


@require_auth
async def pause_site(request: web.Request) -> web.Response:
    site_id = int(request.match_info["site_id"])
    site = get_site_by_id(site_id)
    if site:
        set_site_paused_by_id(site_id, site[1], True)
        log_user_action(BOT_OWNER_ID, f"web: поставил сайт на паузу {site[3]}", "web-admin")
        raise web.HTTPFound(f"/admin/users/{site[1]}")
    raise web.HTTPFound("/admin/users")


@require_auth
async def resume_site(request: web.Request) -> web.Response:
    site_id = int(request.match_info["site_id"])
    site = get_site_by_id(site_id)
    if site:
        set_site_paused_by_id(site_id, site[1], False)
        log_user_action(BOT_OWNER_ID, f"web: возобновил сайт {site[3]}", "web-admin")
        raise web.HTTPFound(f"/admin/users/{site[1]}")
    raise web.HTTPFound("/admin/users")


def create_app(bot) -> web.Application:
    app = web.Application()
    app["bot"] = bot
    app.router.add_get("/admin/login", login_page)
    app.router.add_post("/admin/login", login)
    app.router.add_get("/admin/logout", logout)
    app.router.add_get("/admin", admin_root)
    app.router.add_get("/admin/", dashboard)
    app.router.add_get("/admin/users", users)
    app.router.add_get("/admin/users/{user_id:\\d+}", user_detail)
    app.router.add_post("/admin/users/{user_id:\\d+}/delete", delete_user)
    app.router.add_get("/admin/logs", logs)
    app.router.add_get("/admin/events", events)
    app.router.add_get("/admin/messages", messages)
    app.router.add_post("/admin/messages/send", send_message)
    app.router.add_post("/admin/messages/broadcast", broadcast_message)
    app.router.add_post("/admin/sites/{site_id:\\d+}/delete", delete_site)
    app.router.add_post("/admin/sites/{site_id:\\d+}/pause", pause_site)
    app.router.add_post("/admin/sites/{site_id:\\d+}/resume", resume_site)
    return app


async def start_admin_console(bot):
    if not ADMIN_WEB_TOKEN:
        print("Admin web console disabled: ADMIN_WEB_TOKEN is not set")
        return None

    app = create_app(bot)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, ADMIN_WEB_HOST, ADMIN_WEB_PORT)
    await site.start()
    print(f"Admin web console started on http://{ADMIN_WEB_HOST}:{ADMIN_WEB_PORT}/admin/")
    return runner
