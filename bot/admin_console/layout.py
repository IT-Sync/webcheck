"""Shared HTML layout for the administrative console."""

import html

from aiohttp import web


def esc(value) -> str:
    if value is None:
        return ""
    return html.escape(str(value), quote=True)


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
