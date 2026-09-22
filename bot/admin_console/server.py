import asyncio
import html
import os
from datetime import datetime
from io import BytesIO
from urllib.parse import quote, urlencode

from aiohttp import web
from aiogram.exceptions import TelegramForbiddenError

from bot.agent_server.registry import AGENT_REGISTRY
from bot.webapp.server import WEB_APP_ENABLED, setup_webapp_routes
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
    get_feedback_conversation,
    get_feedback_conversations,
    get_feedback_message,
    get_feedback_messages,
    get_site_by_id,
    get_user_logs,
    log_user_action,
    add_admin_feedback_message,
    mark_feedback_read,
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


def admin_site_status(site: dict) -> tuple[str, str]:
    if site["is_paused"]:
        return "paused", "На паузе"
    status = site.get("last_status") or ""
    if "HTTP: DOWN" in status:
        return "down", "Недоступен"
    if "HTTP: OK" in status:
        return "up", "В сети"
    if status:
        return "warning", "Внимание"
    return "pending", "Ожидает"


def feedback_badge(item: dict) -> str:
    if item["unread_count"]:
        return f'<span class="unread-badge">Новых: {item["unread_count"]}</span>'
    if item["waiting_for_user"]:
        return '<span class="status-warning">Ожидается сообщение</span>'
    if item["status"] == "answered":
        return '<span class="status-ok">Отвечено</span>'
    return '<span class="status-warning">Ожидает ответа</span>'


def feedback_preview(item: dict) -> str:
    if item.get("last_message"):
        return item["last_message"]
    labels = {
        "photo": "Фото",
        "animation": "Анимация",
        "video": "Видео",
        "video_note": "Видеосообщение",
        "document": "Документ",
        "audio": "Аудио",
        "voice": "Голосовое сообщение",
    }
    label = labels.get(item.get("last_media_type"), "Вложение")
    return f"📎 {item.get('last_file_name') or label}"


def feedback_attachment_html(item: dict) -> str:
    if not item.get("telegram_file_id"):
        return ""
    media_url = f"/admin/feedback/media/{item['id']}"
    media_type = item.get("media_type")
    file_name = esc(item.get("file_name") or "Вложение")
    if media_type == "photo":
        return f'<a class="thread-media" href="{media_url}" target="_blank"><img src="{media_url}" loading="lazy" alt="{file_name}"></a>'
    if media_type in {"animation", "video", "video_note"}:
        return f'<video class="thread-media-player" controls preload="metadata" src="{media_url}"></video>'
    if media_type in {"audio", "voice"}:
        return f'<audio class="thread-audio" controls preload="metadata" src="{media_url}"></audio>'
    return f'<a class="attachment-card" href="{media_url}"><span>↓</span><strong>{file_name}</strong><small>Скачать вложение</small></a>'


def redirect_messages(result: str) -> web.HTTPFound:
    return web.HTTPFound("/admin/messages?" + urlencode({"result": result}))


def redirect_agents(result: str) -> web.HTTPFound:
    return web.HTTPFound("/admin/agents?" + urlencode({"result": result}))


def redirect_feedback(conversation_id: int, result: str) -> web.HTTPFound:
    path = f"/admin/feedback/{conversation_id}"
    return web.HTTPFound(path + "?" + urlencode({"result": result}))


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
        ("sites", "/admin/sites", "Сайты"),
        ("feedback", "/admin/feedback", "Обратная связь"),
        ("users", "/admin/users", "Пользователи"),
        ("logs", "/admin/logs", "Логи"),
        ("events", "/admin/events", "События"),
        ("agents", "/admin/agents", "Агенты"),
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
      color-scheme: dark;
      --bg: #07110f;
      --panel: #0c1916;
      --panel-raised: #12231f;
      --text: #e8f1eb;
      --muted: #82978d;
      --line: rgba(210, 235, 222, .14);
      --accent: #b8f34a;
      --cyan: #4ac7b8;
      --danger: #ff6b55;
      --ok: #b8f34a;
      --amber: #ffb547;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background:
        linear-gradient(rgba(184, 243, 74, .025) 1px, transparent 1px),
        linear-gradient(90deg, rgba(184, 243, 74, .025) 1px, transparent 1px),
        var(--bg);
      background-size: 32px 32px;
      color: var(--text);
      font: 14px/1.5 "Aptos", "Segoe UI", sans-serif;
    }}
    header {{
      position: sticky;
      z-index: 5;
      top: 0;
      background: rgba(7, 17, 15, .92);
      color: var(--text);
      padding: 14px clamp(16px, 4vw, 48px);
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      border-bottom: 1px solid var(--line);
      backdrop-filter: blur(18px);
    }}
    header h1 {{ margin: 0; font: 700 20px/1 Georgia, serif; letter-spacing: -.02em; }}
    header h1 span {{ color: var(--accent); }}
    .header-tools {{ display: flex; align-items: center; gap: 10px; }}
    .global-search {{ width: min(280px, 28vw); background: var(--panel) !important; }}
    nav {{
      display: flex;
      gap: 6px;
      overflow-x: auto;
      padding: 12px clamp(16px, 4vw, 48px);
      background: rgba(12, 25, 22, .84);
      border-bottom: 1px solid var(--line);
    }}
    nav a {{
      color: var(--muted);
      text-decoration: none;
      padding: 9px 13px;
      border: 1px solid transparent;
      border-radius: 999px;
      white-space: nowrap;
      font: 700 10px/1 "Courier New", monospace;
      letter-spacing: .08em;
      text-transform: uppercase;
    }}
    nav a.active, nav a:hover {{ border-color: rgba(184, 243, 74, .35); background: rgba(184, 243, 74, .08); color: var(--accent); }}
    main {{ max-width: 1320px; margin: 0 auto; padding: 34px clamp(14px, 4vw, 48px) 70px; }}
    h2 {{ margin: 0 0 16px; font: 400 28px/1.1 Georgia, serif; letter-spacing: -.025em; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 12px; margin-bottom: 24px; }}
    .metric, .panel {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 14px;
      padding: 18px;
    }}
    .metric {{ position: relative; overflow: hidden; min-height: 112px; background: linear-gradient(135deg, var(--panel-raised), var(--panel)); }}
    .metric::after {{ content: ""; position: absolute; right: -28px; bottom: -38px; width: 90px; height: 90px; border: 1px solid rgba(184, 243, 74, .13); border-radius: 50%; }}
    .metric strong {{ display: block; margin-bottom: 16px; color: var(--accent); font: 400 34px/1 Georgia, serif; }}
    .metric span, .muted {{ color: var(--muted); }}
    .metric span {{ font: 700 9px/1.3 "Courier New", monospace; letter-spacing: .08em; text-transform: uppercase; }}
    table {{ width: 100%; border-collapse: separate; border-spacing: 0; overflow: hidden; background: rgba(12, 25, 22, .94); border: 1px solid var(--line); border-radius: 13px; }}
    th, td {{ padding: 12px 13px; border-bottom: 1px solid var(--line); text-align: left; vertical-align: top; }}
    th {{ background: #10201c; color: var(--muted); font: 700 9px/1.2 "Courier New", monospace; letter-spacing: .09em; text-transform: uppercase; }}
    th.sortable {{ cursor: pointer; user-select: none; white-space: nowrap; }}
    th.sortable::after {{ content: "\u2195"; margin-left: 7px; color: rgba(130, 151, 141, .55); font-size: 11px; }}
    th.sortable[aria-sort="ascending"]::after {{ content: "\u2191"; color: var(--accent); }}
    th.sortable[aria-sort="descending"]::after {{ content: "\u2193"; color: var(--accent); }}
    th.sortable:focus-visible {{ outline: 2px solid var(--accent); outline-offset: -3px; }}
    tbody tr {{ transition: background 150ms ease; }}
    tbody tr:hover {{ background: rgba(184, 243, 74, .035); }}
    tr:last-child td {{ border-bottom: 0; }}
    a {{ color: var(--cyan); }}
    code {{ background: rgba(74, 199, 184, .1); color: #8fe0d7; padding: 3px 6px; border-radius: 5px; }}
    form.inline {{ display: inline; }}
    input, textarea, select {{
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 9px;
      padding: 9px 10px;
      font: inherit;
      background: #08120f;
      color: var(--text);
    }}
    textarea {{ min-height: 140px; resize: vertical; }}
    label {{ display: block; margin: 0 0 12px; color: var(--muted); }}
    button, .button {{
      border: 0;
      border-radius: 999px;
      padding: 9px 12px;
      background: var(--accent);
      color: #13200c;
      font: inherit;
      font-weight: 750;
      cursor: pointer;
      text-decoration: none;
      display: inline-block;
    }}
    button.secondary, .button.secondary {{ border: 1px solid var(--line); background: transparent; color: var(--text); }}
    button.danger {{ background: rgba(255, 107, 85, .12); color: #ff8f7e; }}
    .actions {{ display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }}
    .status-ok {{ color: var(--ok); font-weight: 650; }}
    .status-bad {{ color: var(--danger); font-weight: 650; }}
    .status-warning {{ color: var(--amber); font-weight: 650; }}
    .status-muted {{ color: var(--muted); font-weight: 650; }}
    .flash {{ margin-bottom: 16px; padding: 12px 14px; background: rgba(255, 181, 71, .08); border: 1px solid rgba(255, 181, 71, .35); border-radius: 10px; color: #ffd498; }}
    .split {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 16px; }}
    .split > section {{ min-width: 0; overflow-x: auto; }}
    .chart {{
      min-height: 190px;
      display: flex;
      align-items: end;
      gap: 8px;
      padding: 14px 10px 8px;
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 13px;
      overflow-x: auto;
    }}
    .bar-item {{ min-width: 44px; display: grid; gap: 5px; justify-items: center; align-items: end; }}
    .bar {{
      width: 28px;
      border-radius: 5px 5px 0 0;
      background: var(--accent);
    }}
    .bar-value {{ font-size: 12px; color: var(--text); }}
    .bar-label {{ font-size: 11px; color: var(--muted); white-space: nowrap; }}
    .user-head {{ display: flex; justify-content: space-between; align-items: start; gap: 16px; margin-bottom: 16px; }}
    .user-head h2 {{ margin-bottom: 4px; }}
    .subline {{ color: var(--muted); }}
    .registry-head {{ display: flex; align-items: end; justify-content: space-between; gap: 18px; margin-bottom: 18px; }}
    .registry-head h2 {{ margin-bottom: 5px; }}
    .registry-total {{ color: var(--accent); font: 400 34px/1 Georgia, serif; white-space: nowrap; }}
    .registry-total small {{ display: block; margin-top: 5px; color: var(--muted); font: 700 9px/1 "Courier New", monospace; letter-spacing: .09em; text-align: right; text-transform: uppercase; }}
    .registry-tools {{ display: grid; grid-template-columns: minmax(240px, 1fr) minmax(170px, .35fr) auto; gap: 10px; align-items: end; margin-bottom: 14px; padding: 13px; border: 1px solid var(--line); border-radius: 13px; background: rgba(12, 25, 22, .8); }}
    .registry-tools label {{ margin: 0; font: 700 9px/1 "Courier New", monospace; letter-spacing: .09em; text-transform: uppercase; }}
    .registry-tools input, .registry-tools select {{ margin-top: 7px; }}
    .registry-count {{ min-width: 112px; padding: 10px 12px; color: var(--muted); font: 700 10px/1 "Courier New", monospace; text-align: right; white-space: nowrap; }}
    .site-owner {{ display: grid; gap: 3px; }}
    .site-owner a {{ font-weight: 700; text-decoration: none; }}
    .site-owner small {{ color: var(--muted); }}
    .site-address {{ color: var(--text); font: 12px/1.45 "Courier New", monospace; overflow-wrap: anywhere; }}
    .group-chip {{ display: inline-block; padding: 4px 7px; border: 1px solid rgba(74, 199, 184, .28); border-radius: 999px; color: #8fe0d7; font: 700 9px/1 "Courier New", monospace; }}
    .registry-empty {{ padding: 28px; border: 1px dashed var(--line); border-radius: 13px; color: var(--muted); text-align: center; }}
    .feedback-list {{ display: grid; gap: 10px; }}
    .feedback-item {{ display: grid; grid-template-columns: minmax(180px, .7fr) minmax(260px, 1.6fr) auto; gap: 18px; align-items: center; padding: 16px 18px; border: 1px solid var(--line); border-radius: 14px; background: linear-gradient(120deg, rgba(18, 35, 31, .96), rgba(10, 22, 19, .96)); color: var(--text); text-decoration: none; transition: border-color 160ms ease, transform 160ms ease; }}
    .feedback-item:hover {{ border-color: rgba(184, 243, 74, .36); transform: translateY(-1px); }}
    .feedback-item.unread {{ box-shadow: inset 3px 0 var(--accent); }}
    .feedback-person {{ display: grid; gap: 4px; }}
    .feedback-person strong {{ color: var(--text); }}
    .feedback-person small, .feedback-preview small {{ color: var(--muted); }}
    .feedback-preview {{ min-width: 0; }}
    .feedback-preview p {{ overflow: hidden; margin: 4px 0 0; color: #b8c9c0; text-overflow: ellipsis; white-space: nowrap; }}
    .feedback-meta {{ display: grid; justify-items: end; gap: 7px; white-space: nowrap; }}
    .unread-badge {{ padding: 5px 8px; border-radius: 999px; background: var(--accent); color: #13200c; font: 800 9px/1 "Courier New", monospace; }}
    .thread {{ display: grid; gap: 10px; margin: 18px 0; }}
    .thread-message {{ width: min(78%, 760px); padding: 14px 16px; border: 1px solid var(--line); border-radius: 14px 14px 14px 4px; background: var(--panel-raised); }}
    .thread-message.admin {{ justify-self: end; border-color: rgba(184, 243, 74, .25); border-radius: 14px 14px 4px 14px; background: rgba(184, 243, 74, .07); }}
    .thread-message p {{ margin: 7px 0 0; color: #d8e4dd; white-space: pre-wrap; overflow-wrap: anywhere; }}
    .thread-message header {{ position: static; padding: 0; border: 0; background: transparent; backdrop-filter: none; color: var(--muted); font: 700 9px/1 "Courier New", monospace; letter-spacing: .07em; text-transform: uppercase; }}
    .reply-panel {{ margin-top: 18px; }}
    .thread-media {{ display: block; margin-top: 11px; overflow: hidden; border: 1px solid var(--line); border-radius: 11px; background: #07110f; }}
    .thread-media img {{ display: block; width: 100%; max-height: 520px; object-fit: contain; }}
    .thread-media-player {{ display: block; width: 100%; max-height: 520px; margin-top: 11px; border: 1px solid var(--line); border-radius: 11px; background: #020504; }}
    .thread-audio {{ display: block; width: 100%; margin-top: 11px; }}
    .attachment-card {{ display: grid; grid-template-columns: 34px 1fr; gap: 3px 10px; align-items: center; margin-top: 11px; padding: 11px; border: 1px solid rgba(74, 199, 184, .26); border-radius: 10px; background: rgba(74, 199, 184, .06); color: var(--text); text-decoration: none; }}
    .attachment-card > span {{ grid-row: 1 / 3; display: grid; width: 32px; height: 32px; place-items: center; border-radius: 50%; background: var(--cyan); color: #07110f; font-weight: 900; }}
    .attachment-card small {{ color: var(--muted); }}
    @media (max-width: 720px) {{
      header, nav {{ padding-left: 14px; padding-right: 14px; }}
      main {{ padding: 24px 12px 50px; }}
      .global-search {{ display: none; }}
      th, td {{ padding: 8px; }}
      .hide-sm {{ display: none; }}
      .registry-tools {{ grid-template-columns: 1fr; }}
      .registry-count {{ text-align: left; }}
      .feedback-item {{ grid-template-columns: 1fr; gap: 9px; }}
      .feedback-meta {{ justify-items: start; }}
      .thread-message {{ width: 92%; }}
    }}
  </style>
</head>
<body>
  <header>
    <h1>webcheck <span>/ control</span></h1>
    <div class="header-tools">
      <input class="global-search" id="global-search" type="search" placeholder="Поиск на странице">
      <a class="button" href="/admin/logout">Выйти</a>
    </div>
  </header>
  <nav>{nav_html}</nav>
  <main>{body}</main>
  <script>
    const search = document.querySelector('#global-search');
    search?.addEventListener('input', () => {{
      const query = search.value.trim().toLocaleLowerCase('ru');
      if (registrySearch) {{
        registrySearch.value = search.value;
        filterSiteRegistry();
        return;
      }}
      document.querySelectorAll('tbody tr, .feedback-item').forEach((row) => {{
        row.hidden = query && !row.textContent.toLocaleLowerCase('ru').includes(query);
      }});
    }});
    const registrySearch = document.querySelector('#site-registry-search');
    const registryStatus = document.querySelector('#site-registry-status');
    const registryRows = [...document.querySelectorAll('[data-site-row]')];
    const registryCount = document.querySelector('#site-registry-count');
    const registryEmpty = document.querySelector('#site-registry-empty');
    function filterSiteRegistry() {{
      const query = registrySearch?.value.trim().toLocaleLowerCase('ru') || '';
      const status = registryStatus?.value || 'all';
      let visible = 0;
      registryRows.forEach((row) => {{
        const queryMatches = !query || row.textContent.toLocaleLowerCase('ru').includes(query);
        const statusMatches = status === 'all'
          || row.dataset.status === status
          || (status === 'attention' && ['down', 'warning'].includes(row.dataset.status));
        row.hidden = !(queryMatches && statusMatches);
        if (!row.hidden) visible += 1;
      }});
      if (registryCount) registryCount.textContent = `${{visible}} из ${{registryRows.length}}`;
      if (registryEmpty) registryEmpty.hidden = visible !== 0;
    }}
    registrySearch?.addEventListener('input', filterSiteRegistry);
    registryStatus?.addEventListener('change', filterSiteRegistry);
    filterSiteRegistry();

    const tableCollator = new Intl.Collator('ru', {{ numeric: true, sensitivity: 'base' }});
    function sortableValue(text) {{
      const value = text.trim();
      const normalizedNumber = value.replace(/\s/g, '').replace(',', '.');
      if (/^-?\d+(?:\.\d+)?$/.test(normalizedNumber)) {{
        return {{ kind: 'number', value: Number(normalizedNumber) }};
      }}
      if (/^\d{{4}}-\d{{2}}-\d{{2}}(?:\s|T|$)/.test(value)) {{
        const timestamp = Date.parse(value.replace(' ', 'T'));
        if (!Number.isNaN(timestamp)) return {{ kind: 'number', value: timestamp }};
      }}
      return {{ kind: 'text', value }};
    }}
    function compareSortableValues(leftText, rightText) {{
      const left = sortableValue(leftText);
      const right = sortableValue(rightText);
      if (left.kind === 'number' && right.kind === 'number') return left.value - right.value;
      return tableCollator.compare(String(left.value), String(right.value));
    }}
    function initializeSortableTables() {{
      document.querySelectorAll('table').forEach((table) => {{
        const body = table.tBodies[0];
        const headers = [...table.querySelectorAll('thead th')];
        if (!body || !headers.length) return;
        const sortableRows = [...body.rows].filter((row) => !row.querySelector('td[colspan]'));
        if (!sortableRows.length) return;
        headers.forEach((header, columnIndex) => {{
          if (!header.textContent.trim()) return;
          header.classList.add('sortable');
          header.tabIndex = 0;
          header.setAttribute('aria-sort', 'none');
          header.title = 'Сортировать по столбцу';
          const sortColumn = () => {{
            const direction = header.getAttribute('aria-sort') === 'ascending' ? 'descending' : 'ascending';
            headers.forEach((item) => {{
              if (item.classList.contains('sortable')) item.setAttribute('aria-sort', 'none');
            }});
            header.setAttribute('aria-sort', direction);
            const rows = [...body.rows];
            const sortedRows = rows
              .filter((row) => !row.querySelector('td[colspan]'))
              .map((row, originalIndex) => ({{ row, originalIndex }}))
              .sort((left, right) => {{
                const comparison = compareSortableValues(
                  left.row.cells[columnIndex]?.textContent || '',
                  right.row.cells[columnIndex]?.textContent || '',
                );
                return (comparison || left.originalIndex - right.originalIndex) * (direction === 'ascending' ? 1 : -1);
              }});
            const queue = sortedRows.map((item) => item.row);
            rows.forEach((row) => body.append(row.querySelector('td[colspan]') ? row : queue.shift()));
          }};
          header.addEventListener('click', sortColumn);
          header.addEventListener('keydown', (event) => {{
            if (event.key !== 'Enter' && event.key !== ' ') return;
            event.preventDefault();
            sortColumn();
          }});
        }});
      }});
    }}
    initializeSortableTables();
  </script>
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
    :root {{ color-scheme: dark; }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; min-height: 100vh; display: grid; place-items: center; background: linear-gradient(rgba(184,243,74,.025) 1px, transparent 1px), linear-gradient(90deg, rgba(184,243,74,.025) 1px, transparent 1px), #07110f; background-size: 32px 32px; color: #e8f1eb; font: 14px "Aptos", "Segoe UI", sans-serif; }}
    main {{ position: relative; width: min(440px, calc(100vw - 32px)); overflow: hidden; background: linear-gradient(145deg, #12231f, #0c1916); border: 1px solid rgba(210,235,222,.14); border-radius: 20px; padding: 30px; box-shadow: 0 30px 90px rgba(0,0,0,.35); }}
    main::after {{ content: ""; position: absolute; right: -70px; top: -70px; width: 190px; height: 190px; border: 1px solid rgba(184,243,74,.16); border-radius: 50%; box-shadow: inset 0 0 60px rgba(184,243,74,.04); }}
    h1 {{ position: relative; z-index: 1; margin: 0 0 8px; font: 400 34px/1 Georgia, serif; }}
    h1 span {{ color: #b8f34a; }}
    .login-copy {{ margin: 0 0 24px; color: #82978d; }}
    label {{ display: block; margin-bottom: 14px; }}
    input {{ width: 100%; border: 1px solid rgba(210,235,222,.14); border-radius: 10px; padding: 12px; background: #08120f; color: #e8f1eb; font: inherit; outline: 0; }}
    input:focus {{ border-color: #b8f34a; box-shadow: 0 0 0 3px rgba(184,243,74,.08); }}
    button {{ width: 100%; border: 0; border-radius: 999px; padding: 12px; background: #b8f34a; color: #13200c; font: inherit; font-weight: 800; cursor: pointer; }}
    .flash {{ margin-bottom: 14px; padding: 10px; background: rgba(255,107,85,.1); border: 1px solid rgba(255,107,85,.35); border-radius: 8px; color: #ff9b8c; }}
  </style>
</head>
<body>
  <main>
    <h1>webcheck <span>/ control</span></h1>
    <p class="login-copy">Защищённый вход в операторскую консоль</p>
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
async def sites(request: web.Request) -> web.Response:
    rows = get_admin_sites()
    priority = {"down": 0, "warning": 1, "pending": 2, "up": 3, "paused": 4}
    decorated_rows = [(*admin_site_status(site), site) for site in rows]
    decorated_rows.sort(
        key=lambda item: (
            priority[item[0]],
            (item[2].get("url") or "").casefold(),
            item[2]["id"],
        )
    )
    status_classes = {
        "up": "status-ok",
        "down": "status-bad",
        "warning": "status-warning",
        "paused": "status-muted",
        "pending": "status-muted",
    }
    table_rows = "".join(
        f"""<tr data-site-row data-status="{status_kind}">
  <td><span class="site-address">{esc(site['url'])}</span></td>
  <td><div class="site-owner"><a href="/admin/users/{site['user_id']}">{esc('@' + site['username'] if site['username'] else 'без username')}</a><small>User ID: {site['user_id']}</small></div></td>
  <td>{f'<span class="group-chip">{esc(site["site_group"])}</span>' if site['site_group'] else '<span class="muted">—</span>'}</td>
  <td><span class="{status_classes[status_kind]}">{status_label}</span></td>
  <td>{fmt_dt(site['last_checked'])}</td>
  <td class="hide-sm">{esc((site['last_status'] or 'нет данных')[:180])}</td>
  <td class="actions">
    <a class="button" href="/admin/users/{site['user_id']}">Открыть</a>
    <a class="button secondary" href="/admin/messages?user_id={site['user_id']}">Сообщение</a>
  </td>
</tr>"""
        for status_kind, status_label, site in decorated_rows
    )
    body = f"""
<div class="registry-head">
  <div>
    <h2>Все сайты пользователей</h2>
    <div class="subline">Единый реестр ресурсов с быстрым переходом к владельцу</div>
  </div>
  <div class="registry-total">{len(rows)}<small>ресурсов</small></div>
</div>
<section class="registry-tools" aria-label="Поиск и фильтры ресурсов">
  <label>Поиск<input id="site-registry-search" type="search" placeholder="Домен, username, User ID или группа" autocomplete="off" autofocus></label>
  <label>Состояние<select id="site-registry-status">
    <option value="all">Все состояния</option>
    <option value="attention">Требуют внимания</option>
    <option value="down">Недоступны</option>
    <option value="up">В сети</option>
    <option value="pending">Ожидают проверки</option>
    <option value="paused">На паузе</option>
  </select></label>
  <div class="registry-count" id="site-registry-count">{len(rows)} из {len(rows)}</div>
</section>
<div style="overflow-x:auto">
  <table id="site-registry">
    <thead><tr><th>Ресурс</th><th>Владелец</th><th>Группа</th><th>Состояние</th><th>Проверка</th><th class="hide-sm">Последний результат</th><th></th></tr></thead>
    <tbody>{table_rows}</tbody>
  </table>
</div>
<div class="registry-empty" id="site-registry-empty" hidden>По этому запросу ресурсы не найдены.</div>"""
    return page("Все сайты", body, "sites")


@require_auth
async def feedback(request: web.Request) -> web.Response:
    conversations = get_feedback_conversations()
    conversation_rows = "".join(
        f"""<a class="feedback-item {'unread' if item['unread_count'] else ''}" href="/admin/feedback/{item['id']}">
  <span class="feedback-person">
    <strong>{esc('@' + item['username'] if item['username'] else 'без username')}</strong>
    <small>User ID: {item['user_id']} · обращение #{item['id']}</small>
  </span>
  <span class="feedback-preview">
    <small>{'Пользователь' if item['last_sender'] == 'user' else 'Администратор'}</small>
    <p>{esc(feedback_preview(item))}</p>
  </span>
  <span class="feedback-meta">
    <small>{fmt_dt(item['last_message_created_at'])}</small>
    {feedback_badge(item)}
  </span>
</a>"""
        for item in conversations
    ) or '<div class="registry-empty">Обращений пока нет.</div>'
    unread_total = sum(item["unread_count"] for item in conversations)
    body = f"""
<div class="registry-head">
  <div>
    <h2>Обратная связь</h2>
    <div class="subline">Диалоги пользователей с ответами от имени Telegram-бота</div>
  </div>
  <div class="registry-total">{unread_total}<small>непрочитанных</small></div>
</div>
<div class="feedback-list">{conversation_rows}</div>"""
    return page("Обратная связь", body, "feedback")


@require_auth
async def feedback_detail(request: web.Request) -> web.Response:
    conversation_id = int(request.match_info["conversation_id"])
    conversation = get_feedback_conversation(conversation_id)
    if not conversation:
        raise web.HTTPNotFound(text="Обращение не найдено")
    messages = get_feedback_messages(conversation_id)
    mark_feedback_read(conversation_id)
    username = f"@{conversation['username']}" if conversation["username"] else "без username"
    message_rows = "".join(
        f"""<article class="thread-message {'admin' if item['sender'] == 'admin' else 'user'}">
  <header><span>{'Администратор' if item['sender'] == 'admin' else esc(username)}</span><time>{fmt_dt(item['created_at'])}</time></header>
  {f'<p>{esc(item["message_text"])}</p>' if item['message_text'] else ''}
  {feedback_attachment_html(item)}
</article>"""
        for item in messages
    ) or '<div class="registry-empty">Сообщений пока нет.</div>'
    flash = esc(request.query.get("result", ""))
    flash_html = f'<div class="flash">{flash}</div>' if flash else ""
    body = f"""
<div class="user-head">
  <div>
    <h2>{esc(username)}</h2>
    <div class="subline">Обращение #{conversation_id} · User ID: <code>{conversation['user_id']}</code></div>
  </div>
  <div class="actions">
    <a class="button secondary" href="/admin/feedback">← Все обращения</a>
    <a class="button secondary" href="/admin/users/{conversation['user_id']}">Пользователь</a>
  </div>
</div>
{flash_html}
<section class="thread">{message_rows}</section>
<section class="panel reply-panel">
  <h2>Ответить от имени бота</h2>
  <form method="post" action="/admin/feedback/{conversation_id}/reply">
    <label>Сообщение<textarea name="text" maxlength="3500" required placeholder="Ответ будет отправлен пользователю в Telegram"></textarea></label>
    <button type="submit">Отправить ответ</button>
  </form>
</section>"""
    return page(f"Обращение #{conversation_id}", body, "feedback")


@require_auth
async def reply_feedback(request: web.Request) -> web.Response:
    conversation_id = int(request.match_info["conversation_id"])
    conversation = get_feedback_conversation(conversation_id)
    if not conversation:
        raise web.HTTPNotFound(text="Обращение не найдено")
    data = await request.post()
    text = str(data.get("text") or "").strip()
    if not text:
        raise redirect_feedback(conversation_id, "Ответ не может быть пустым")
    if len(text) > 3500:
        raise redirect_feedback(conversation_id, "Ответ не должен превышать 3500 символов")
    try:
        await request.app["bot"].send_message(
            conversation["user_id"],
            f"💬 Ответ администратора Webcheck:\n\n{text}\n\n"
            "Чтобы продолжить диалог, используйте /feedback или кнопку "
            "«Обратная связь» в приложении.",
        )
    except TelegramForbiddenError:
        raise redirect_feedback(conversation_id, "Пользователь заблокировал бота")
    except Exception as exc:
        raise redirect_feedback(
            conversation_id,
            f"Не удалось отправить ответ: {type(exc).__name__}",
        )
    add_admin_feedback_message(conversation_id, text)
    log_user_action(
        BOT_OWNER_ID,
        f"web: replied to feedback conversation {conversation_id}",
        "web-admin",
    )
    raise redirect_feedback(conversation_id, "Ответ отправлен пользователю")


@require_auth
async def feedback_media(request: web.Request) -> web.Response:
    message_id = int(request.match_info["message_id"])
    item = get_feedback_message(message_id)
    if not item or not item.get("telegram_file_id"):
        raise web.HTTPNotFound(text="Вложение не найдено")
    destination = BytesIO()
    try:
        await request.app["bot"].download(
            item["telegram_file_id"],
            destination=destination,
            timeout=45,
        )
    except Exception as exc:
        raise web.HTTPBadGateway(
            text=f"Не удалось загрузить вложение из Telegram: {type(exc).__name__}"
        )
    safe_inline_types = {
        "image/jpeg", "image/png", "image/webp", "image/gif",
        "video/mp4", "video/webm", "audio/mpeg", "audio/ogg", "audio/mp4",
    }
    mime_type = item.get("mime_type") or "application/octet-stream"
    inline = item.get("media_type") != "document" and mime_type in safe_inline_types
    if not inline:
        mime_type = "application/octet-stream"
    file_name = item.get("file_name") or f"feedback-{message_id}"
    disposition = "inline" if inline else "attachment"
    return web.Response(
        body=destination.getvalue(),
        content_type=mime_type,
        headers={
            "Cache-Control": "private, max-age=300",
            "Content-Disposition": f"{disposition}; filename*=UTF-8''{quote(file_name, safe='')}",
            "X-Content-Type-Options": "nosniff",
        },
    )


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
  <td>{esc(site['site_group'] or '—')}</td>
  <td>{'<span class="status-bad">пауза</span>' if site['is_paused'] else '<span class="status-ok">активен</span>'}</td>
  <td>{fmt_dt(site['last_checked'])}</td>
  <td>{esc((site['last_status'] or 'нет данных')[:240])}</td>
  <td class="actions">
    <form class="inline" method="post" action="/admin/sites/{site['id']}/{'resume' if site['is_paused'] else 'pause'}"><button class="secondary" type="submit">{'Возобновить' if site['is_paused'] else 'Пауза'}</button></form>
    <form class="inline" method="post" action="/admin/sites/{site['id']}/delete"><button class="danger" type="submit">Удалить</button></form>
  </td>
</tr>"""
        for site in sites
    ) or '<tr><td colspan="6">Сайтов нет</td></tr>'
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
<table><thead><tr><th>URL</th><th>Группа</th><th>Статус</th><th>Проверка</th><th>Последний результат</th><th></th></tr></thead><tbody>{site_rows}</tbody></table>
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
async def agents(request: web.Request) -> web.Response:
    rows = await AGENT_REGISTRY.list_agents()
    disabled_agents = await AGENT_REGISTRY.list_disabled()
    results = await AGENT_REGISTRY.recent_results()
    flash = esc(request.query.get("result", ""))
    flash_html = f'<div class="flash">{flash}</div>' if flash else ""
    options = "".join(
        f"<option value=\"{esc(row['agent_id'])}\">{esc(row['agent_id'])} · {esc(row['country'])} {esc(row['region'])}</option>"
        for row in rows
    )
    check_form = (
        f"""<section class="panel" style="margin-bottom:16px">
  <h2>Отправить задание агенту</h2>
  <form method="post" action="/admin/agents/check">
    <label>Агент<select name="agent_id" required>{options}</select></label>
    <label>URL<input name="url" placeholder="https://example.com" required></label>
    <label>Timeout, сек<input name="timeout_sec" value="45" inputmode="numeric"></label>
    <button type="submit">Проверить</button>
  </form>
</section>"""
        if rows else ""
    )
    table = "".join(
        f"""<tr>
  <td><code>{esc(row['agent_id'])}</code></td>
  <td>{esc(row['country'])}</td>
  <td>{esc(row['region'])}</td>
  <td>{esc(row['provider'])}</td>
  <td>{fmt_dt(row['connected_at'])}</td>
  <td>{fmt_dt(row['last_seen_at'])}</td>
  <td>{fmt_dt(row['last_result_at'])}</td>
  <td>{esc(row['remote'])}</td>
  <td><form class="inline" method="post" action="/admin/agents/{quote(row['agent_id'], safe='')}/disable"><button class="danger" type="submit">Отключить</button></form></td>
</tr>"""
        for row in rows
    ) or '<tr><td colspan="9">Онлайн-агентов нет</td></tr>'
    disabled_rows = "".join(
        f"""<tr>
  <td><code>{esc(agent_id)}</code></td>
  <td><form class="inline" method="post" action="/admin/agents/{quote(agent_id, safe='')}/enable"><button type="submit">Включить</button></form></td>
</tr>"""
        for agent_id in disabled_agents
    ) or '<tr><td colspan="2">Отключённых агентов нет</td></tr>'
    result_rows = "".join(
        f"""<tr>
  <td>{fmt_dt(row['received_at'])}</td>
  <td><code>{esc(row['agent_id'])}</code></td>
  <td>{esc(row['country'])}</td>
  <td>{esc(row['url'])}</td>
  <td>{'<span class="status-ok">OK</span>' if row['ok'] else '<span class="status-bad">DOWN</span>'}</td>
  <td>{esc(row['error'] or '')}</td>
</tr>"""
        for row in results[:30]
    ) or '<tr><td colspan="6">Результатов пока нет</td></tr>'
    body = f"""
<h2>Агенты</h2>
{flash_html}
{check_form}
<table>
  <thead><tr><th>Agent ID</th><th>Страна</th><th>Регион</th><th>Provider</th><th>Подключён</th><th>Heartbeat</th><th>Результат</th><th>Remote</th><th></th></tr></thead>
  <tbody>{table}</tbody>
</table>
<h2 style="margin-top:24px">Отключённые агенты</h2>
<table>
  <thead><tr><th>Agent ID</th><th></th></tr></thead>
  <tbody>{disabled_rows}</tbody>
</table>
<h2 style="margin-top:24px">Последние результаты</h2>
<table>
  <thead><tr><th>Дата</th><th>Agent ID</th><th>Страна</th><th>URL</th><th>Статус</th><th>Ошибка</th></tr></thead>
  <tbody>{result_rows}</tbody>
</table>"""
    return page("Агенты", body, "agents")


@require_auth
async def send_agent_check(request: web.Request) -> web.Response:
    data = await request.post()
    agent_id = str(data.get("agent_id") or "").strip()
    url = str(data.get("url") or "").strip()
    try:
        timeout_sec = int(data.get("timeout_sec") or 45)
    except ValueError:
        timeout_sec = 45
    if not agent_id or not url:
        raise redirect_agents("Укажите агента и URL")
    try:
        job_id = await AGENT_REGISTRY.send_check(
            agent_id,
            url,
            checks=["http", "ssl", "domain"],
            timeout_sec=timeout_sec,
        )
    except KeyError:
        raise redirect_agents("Агент не online")
    except Exception as e:
        raise redirect_agents(f"Не удалось отправить задание: {type(e).__name__}: {e}")
    raise redirect_agents(f"Задание отправлено агенту {agent_id}, job_id={job_id}")


@require_auth
async def disable_agent(request: web.Request) -> web.Response:
    agent_id = request.match_info["agent_id"]
    await AGENT_REGISTRY.disable(agent_id)
    raise redirect_agents(f"Агент {agent_id} отключён")


@require_auth
async def enable_agent(request: web.Request) -> web.Response:
    agent_id = request.match_info["agent_id"]
    await AGENT_REGISTRY.enable(agent_id)
    raise redirect_agents(f"Агент {agent_id} включён. Он подключится при следующей попытке reconnect.")


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
    app = web.Application(client_max_size=64 * 1024)
    app["bot"] = bot
    app.router.add_get("/admin/login", login_page)
    app.router.add_post("/admin/login", login)
    app.router.add_get("/admin/logout", logout)
    app.router.add_get("/admin", admin_root)
    app.router.add_get("/admin/", dashboard)
    app.router.add_get("/admin/sites", sites)
    app.router.add_get("/admin/feedback", feedback)
    app.router.add_get("/admin/feedback/media/{message_id:\\d+}", feedback_media)
    app.router.add_get("/admin/feedback/{conversation_id:\\d+}", feedback_detail)
    app.router.add_post("/admin/feedback/{conversation_id:\\d+}/reply", reply_feedback)
    app.router.add_get("/admin/users", users)
    app.router.add_get("/admin/users/{user_id:\\d+}", user_detail)
    app.router.add_post("/admin/users/{user_id:\\d+}/delete", delete_user)
    app.router.add_get("/admin/logs", logs)
    app.router.add_get("/admin/events", events)
    app.router.add_get("/admin/agents", agents)
    app.router.add_post("/admin/agents/check", send_agent_check)
    app.router.add_post("/admin/agents/{agent_id}/disable", disable_agent)
    app.router.add_post("/admin/agents/{agent_id}/enable", enable_agent)
    app.router.add_get("/admin/messages", messages)
    app.router.add_post("/admin/messages/send", send_message)
    app.router.add_post("/admin/messages/broadcast", broadcast_message)
    app.router.add_post("/admin/sites/{site_id:\\d+}/delete", delete_site)
    app.router.add_post("/admin/sites/{site_id:\\d+}/pause", pause_site)
    app.router.add_post("/admin/sites/{site_id:\\d+}/resume", resume_site)
    setup_webapp_routes(app)
    return app


async def start_admin_console(bot):
    if not ADMIN_WEB_TOKEN and not WEB_APP_ENABLED:
        print("Web server disabled: ADMIN_WEB_TOKEN is not set and WEB_APP_ENABLED=0")
        return None

    app = create_app(bot)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, ADMIN_WEB_HOST, ADMIN_WEB_PORT)
    await site.start()
    if ADMIN_WEB_TOKEN:
        print(f"Admin web console started on http://{ADMIN_WEB_HOST}:{ADMIN_WEB_PORT}/admin/")
    if WEB_APP_ENABLED:
        print(f"Telegram Mini App started on http://{ADMIN_WEB_HOST}:{ADMIN_WEB_PORT}/app/")
    return runner
