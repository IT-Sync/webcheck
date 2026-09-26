import asyncio
from html import escape

from aiohttp import web

from bot.infra.db import get_public_status_page


STATUS_LABELS = {
    "operational": ("Operational", "ok"), "outage": ("Outage", "down"),
    "degraded": ("Degraded", "warn"), "maintenance": ("Maintenance", "maint"),
    "paused": ("Monitoring paused", "muted"),
}


def _time(value):
    return value.strftime("%d %b %Y · %H:%M UTC") if value else "Awaiting first check"


def render_status_page(page):
    services = "".join(
        f'''<li><span><i class="dot {STATUS_LABELS[item["status"]][1]}"></i>{escape(item["name"])}</span>
        <b>{STATUS_LABELS[item["status"]][0]}</b><time>{_time(item["last_checked"])}</time></li>'''
        for item in page["services"]
    )
    updates = "".join(
        f'''<article><time>{_time(item["created_at"])}</time><p>{escape(item["message"])}</p></article>'''
        for item in page["updates"]
    ) or '<p class="quiet">No operator updates have been published.</p>'
    healthy = bool(page["services"]) and all(
        item["status"] == "operational" for item in page["services"]
    )
    headline = "All selected services operational" if healthy else "Some selected services need attention"
    tone = "ok" if healthy else "warn"
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="index,follow">
<title>{escape(page["name"])} · Service status</title><style>
:root{{--ink:#07110f;--paper:#e8eee8;--acid:#a8ff78;--amber:#ffcf66;--line:#bdd0c4;--muted:#52655d}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--paper);color:var(--ink);font:15px/1.5 Georgia,serif}}
body:before{{content:"";position:fixed;inset:0;pointer-events:none;opacity:.28;background-image:linear-gradient(#fff8 1px,transparent 1px),linear-gradient(90deg,#fff8 1px,transparent 1px);background-size:28px 28px}}
main{{position:relative;width:min(920px,calc(100% - 32px));margin:0 auto;padding:54px 0 80px}}
header{{display:grid;grid-template-columns:1fr auto;gap:20px;align-items:start;border-top:8px solid var(--ink);padding-top:22px}}
.kicker,time{{font:11px/1.2 ui-monospace,SFMono-Regular,monospace;text-transform:uppercase;letter-spacing:.09em;color:var(--muted)}}
h1{{font-size:clamp(42px,8vw,82px);line-height:.9;letter-spacing:-.055em;margin:14px 0}}.description{{max-width:620px;font-size:18px}}
.signal{{width:82px;aspect-ratio:1;border-radius:50%;display:grid;place-items:center;background:var(--ink);color:var(--acid);font:700 11px ui-monospace,monospace;box-shadow:0 0 0 9px #cad8ce,0 0 0 10px var(--ink)}}
.summary{{margin:50px 0 18px;padding:22px 24px;border:1px solid var(--ink);display:flex;gap:14px;align-items:center;background:#f7faf6;box-shadow:7px 7px 0 var(--ink);font-size:20px}}
.dot{{display:inline-block;width:10px;height:10px;border-radius:50%;background:var(--muted)}}.dot.ok{{background:#42a65a;box-shadow:0 0 0 4px #42a65a22}}.dot.down{{background:#d84535}}.dot.warn{{background:#d99321}}.dot.maint{{background:#287f9d}}
ul{{list-style:none;margin:0;padding:0;border-top:1px solid var(--line)}}li{{display:grid;grid-template-columns:1fr auto;gap:5px 20px;padding:20px 4px;border-bottom:1px solid var(--line)}}li span{{font-size:18px}}li .dot{{margin-right:12px}}li b{{font:700 12px ui-monospace,monospace;text-transform:uppercase}}li time{{grid-column:1/-1;margin-left:22px}}
h2{{font-size:30px;letter-spacing:-.03em;margin:58px 0 16px}}article{{border-left:3px solid var(--ink);padding:3px 0 3px 18px;margin:20px 0}}article p{{white-space:pre-wrap;margin:8px 0 0;font-size:17px}}.quiet{{color:var(--muted)}}
footer{{margin-top:70px;padding-top:14px;border-top:1px solid var(--ink);display:flex;justify-content:space-between;font:11px ui-monospace,monospace;text-transform:uppercase}}
@media(max-width:560px){{main{{padding-top:30px}}header{{grid-template-columns:1fr}}.signal{{display:none}}li{{grid-template-columns:1fr}}li b{{grid-row:2}}}}
</style></head><body><main><header><div><p class="kicker">Public service ledger / verified selection</p>
<h1>{escape(page["name"])}</h1><p class="description">{escape(page["description"])}</p></div><div class="signal">LIVE</div></header>
<section class="summary"><i class="dot {tone}"></i><strong>{headline}</strong></section>
<ul>{services}</ul><h2>Operator updates</h2><section>{updates}</section>
<footer><span>Webcheck public status</span><span>Updated {_time(page["updated_at"])}</span></footer></main></body></html>'''


async def public_status_page(request):
    page = await asyncio.to_thread(get_public_status_page, request.match_info["slug"])
    if page is None:
        raise web.HTTPNotFound()
    return web.Response(text=render_status_page(page), content_type="text/html",
                        headers={"Cache-Control": "public, max-age=30"})


def setup_public_status_routes(app):
    app.router.add_get("/status/{slug:[a-z0-9][a-z0-9-]{2,62}}", public_status_page)
