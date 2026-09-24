import asyncio
import os
from datetime import datetime
from functools import wraps
from pathlib import Path

from aiohttp import web

from bot.agent_server.checks import check_with_agents
from bot.checks.service import check_resource
from bot.core.status_formatter import append_agent_results, format_status_text
from bot.infra.db import (
    add_site,
    delete_site_by_id,
    get_site_by_url_for_user,
    get_site_for_user,
    get_site_history_for_user,
    get_sites_with_pause,
    log_user_action,
    start_feedback_waiting,
    cancel_feedback_waiting,
    set_site_paused_by_id,
    set_site_group_by_id,
    update_site_status_by_id,
)
from bot.webapp.auth import TelegramAuthError, validate_init_data
from bot.webapp.validation import TargetValidationError, validate_monitoring_target


BOT_TOKEN = os.getenv("BOT_TOKEN", "")
WEB_APP_ENABLED = os.getenv("WEB_APP_ENABLED", "1") == "1"
WEB_APP_AUTH_MAX_AGE_SECONDS = int(os.getenv("WEB_APP_AUTH_MAX_AGE_SECONDS", "86400"))
WEB_APP_MAX_SITES_PER_USER = int(os.getenv("WEB_APP_MAX_SITES_PER_USER", "50"))
WEB_APP_DNS_TIMEOUT_SECONDS = float(os.getenv("WEB_APP_DNS_TIMEOUT_SECONDS", "3"))
WEB_APP_CHECK_TIMEOUT_SECONDS = int(os.getenv("WEB_APP_CHECK_TIMEOUT_SECONDS", "10"))
WEB_APP_AGENT_TIMEOUT_SECONDS = int(os.getenv("WEB_APP_AGENT_TIMEOUT_SECONDS", "5"))
STATIC_DIR = Path(__file__).with_name("static")

_check_locks: dict[int, asyncio.Lock] = {}


def _json_error(message: str, *, status: int = 400, code: str = "bad_request"):
    return web.json_response({"ok": False, "error": {"code": code, "message": message}}, status=status)


def _extract_init_data(request: web.Request) -> str:
    authorization = request.headers.get("Authorization", "")
    if authorization.lower().startswith("tma "):
        return authorization[4:].strip()
    return request.headers.get("X-Telegram-Init-Data", "").strip()


def require_telegram_user(handler):
    @wraps(handler)
    async def wrapped(request: web.Request):
        try:
            request["telegram_user"] = validate_init_data(
                _extract_init_data(request),
                BOT_TOKEN,
                max_age_seconds=WEB_APP_AUTH_MAX_AGE_SECONDS,
            )
        except TelegramAuthError:
            return _json_error(
                "Сессия Telegram недействительна. Закройте и снова откройте приложение из бота.",
                status=401,
                code="unauthorized",
            )
        return await handler(request)

    return wrapped


def _iso(value):
    return value.isoformat() + "Z" if isinstance(value, datetime) else None


def _status_kind(status: str | None, paused: bool) -> str:
    if paused:
        return "paused"
    if not status:
        return "pending"
    if "HTTP: OK" in status:
        return "up"
    if "HTTP: DOWN" in status:
        return "down"
    return "warning"


def _site_payload(row: tuple) -> dict:
    paused = bool(row[6])
    return {
        "id": row[0],
        "url": row[3],
        "last_status": row[4],
        "last_checked": _iso(row[5]),
        "is_paused": paused,
        "status_kind": _status_kind(row[4], paused),
        "site_group": row[7] if len(row) > 7 else "",
    }


def _clean_group(value) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError("Группа должна быть строкой")
    group = " ".join(value.strip().split())
    if len(group) > 40:
        raise ValueError("Название группы не должно превышать 40 символов")
    return group


def _site_payload_for_user(site_id: int, user_id: int) -> dict | None:
    row = next((item for item in get_sites_with_pause(user_id) if item[0] == site_id), None)
    return _site_payload(row) if row else None


async def app_index(request: web.Request) -> web.FileResponse:
    if not WEB_APP_ENABLED:
        raise web.HTTPNotFound()
    response = web.FileResponse(STATIC_DIR / "index.html")
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


async def app_redirect(request: web.Request) -> web.HTTPFound:
    raise web.HTTPFound("/app/")


@require_telegram_user
async def bootstrap(request: web.Request) -> web.Response:
    user = request["telegram_user"]
    rows = get_sites_with_pause(user.id)
    sites = [_site_payload(row) for row in rows]
    groups = sorted({site["site_group"] for site in sites if site["site_group"]}, key=str.casefold)
    metrics = {
        "total": len(sites),
        "up": sum(site["status_kind"] == "up" for site in sites),
        "attention": sum(site["status_kind"] in {"down", "warning"} for site in sites),
        "paused": sum(site["is_paused"] for site in sites),
    }
    return web.json_response(
        {
            "ok": True,
            "user": {
                "id": user.id,
                "username": user.username,
                "first_name": user.first_name,
                "last_name": user.last_name,
            },
            "sites": sites,
            "groups": groups,
            "metrics": metrics,
            "limits": {"sites": WEB_APP_MAX_SITES_PER_USER},
        }
    )


@require_telegram_user
async def start_feedback(request: web.Request) -> web.Response:
    user = request["telegram_user"]
    try:
        conversation_id = start_feedback_waiting(user.id, user.username)
    except Exception as exc:
        return _json_error(
            f"Не удалось открыть обратную связь: {type(exc).__name__}",
            status=503,
            code="feedback_unavailable",
        )
    try:
        await request.app["bot"].send_message(
            user.id,
            "💬 Отправьте ваш вопрос, пожелание или описание проблемы. "
            "Можно приложить фото, видео, документ, аудио или голосовое сообщение.\n\n"
            "Следующее сообщение будет отправлено администратору. "
            "Чтобы отменить отправку, используйте /cancel_feedback.",
        )
    except Exception as exc:
        cancel_feedback_waiting(user.id)
        return _json_error(
            f"Не удалось открыть обратную связь: {type(exc).__name__}",
            status=502,
            code="feedback_start_failed",
        )
    log_user_action(user.id, "Mini App: started feedback", user.username)
    return web.json_response({"ok": True, "conversation_id": conversation_id})


@require_telegram_user
async def create_site(request: web.Request) -> web.Response:
    user = request["telegram_user"]
    try:
        data = await request.json()
    except Exception:
        return _json_error("Ожидалось тело запроса в формате JSON")
    if not isinstance(data, dict):
        return _json_error("Ожидался JSON-объект")

    if len(get_sites_with_pause(user.id)) >= WEB_APP_MAX_SITES_PER_USER:
        return _json_error(
            f"Достигнут лимит: {WEB_APP_MAX_SITES_PER_USER} сайтов",
            status=409,
            code="site_limit",
        )

    try:
        url = await validate_monitoring_target(
            data.get("url", ""),
            dns_timeout_seconds=WEB_APP_DNS_TIMEOUT_SECONDS,
        )
    except TargetValidationError as exc:
        return _json_error(str(exc), code="invalid_target")
    try:
        site_group = _clean_group(data.get("site_group", ""))
    except ValueError as exc:
        return _json_error(str(exc), code="invalid_group")

    existing = get_site_by_url_for_user(user.id, url)
    if existing:
        return _json_error("Этот сайт уже добавлен", status=409, code="duplicate")

    site_id = add_site(user.id, url, user.username, site_group)
    log_user_action(user.id, f"Mini App: added site {url}", user.username)
    site = _site_payload_for_user(site_id, user.id)
    return web.json_response({"ok": True, "site": site}, status=201)


def _owned_site(request: web.Request):
    user = request["telegram_user"]
    try:
        site_id = int(request.match_info["site_id"])
    except (KeyError, ValueError):
        return None
    return get_site_for_user(site_id, user.id)


@require_telegram_user
async def pause_site(request: web.Request) -> web.Response:
    user = request["telegram_user"]
    site = _owned_site(request)
    if not site:
        return _json_error("Сайт не найден", status=404, code="not_found")
    set_site_paused_by_id(site[0], user.id, True)
    log_user_action(user.id, f"Mini App: paused site {site[3]}", user.username)
    return web.json_response({"ok": True})


@require_telegram_user
async def resume_site(request: web.Request) -> web.Response:
    user = request["telegram_user"]
    site = _owned_site(request)
    if not site:
        return _json_error("Сайт не найден", status=404, code="not_found")
    set_site_paused_by_id(site[0], user.id, False)
    log_user_action(user.id, f"Mini App: resumed site {site[3]}", user.username)
    return web.json_response({"ok": True})


@require_telegram_user
async def delete_site(request: web.Request) -> web.Response:
    user = request["telegram_user"]
    site = _owned_site(request)
    if not site:
        return _json_error("Сайт не найден", status=404, code="not_found")
    delete_site_by_id(site[0], user.id)
    log_user_action(user.id, f"Mini App: deleted site {site[3]}", user.username)
    return web.json_response({"ok": True})


@require_telegram_user
async def update_site_group(request: web.Request) -> web.Response:
    user = request["telegram_user"]
    site = _owned_site(request)
    if not site:
        return _json_error("Сайт не найден", status=404, code="not_found")
    try:
        data = await request.json()
        if not isinstance(data, dict):
            raise ValueError("Ожидался JSON-объект")
        site_group = _clean_group(data.get("site_group", ""))
    except (ValueError, TypeError, AttributeError) as exc:
        return _json_error(str(exc), code="invalid_group")
    set_site_group_by_id(site[0], user.id, site_group)
    log_user_action(user.id, f"Mini App: changed group for {site[3]} to {site_group or 'none'}", user.username)
    return web.json_response({"ok": True, "site": _site_payload_for_user(site[0], user.id)})


@require_telegram_user
async def site_history(request: web.Request) -> web.Response:
    user = request["telegram_user"]
    try:
        site_id = int(request.match_info["site_id"])
        days = int(request.query.get("days", "7"))
    except (KeyError, ValueError):
        return _json_error("Некорректный период", code="invalid_period")
    history = get_site_history_for_user(site_id, user.id, days=days)
    if history is None:
        return _json_error("Сайт не найден", status=404, code="not_found")
    for point in history["points"]:
        point["bucket_start"] = _iso(point["bucket_start"])
    for incident in history["incidents"]:
        incident["started_at"] = _iso(incident["started_at"])
        incident["ended_at"] = _iso(incident["ended_at"])
    for event in history["events"]:
        event["created_at"] = _iso(event["created_at"])
    return web.json_response({"ok": True, "history": history})


@require_telegram_user
async def check_site(request: web.Request) -> web.Response:
    user = request["telegram_user"]
    site = _owned_site(request)
    if not site:
        return _json_error("Сайт не найден", status=404, code="not_found")

    lock = _check_locks.setdefault(site[0], asyncio.Lock())
    if lock.locked():
        return _json_error("Проверка уже выполняется", status=409, code="check_running")

    async with lock:
        try:
            result = await check_resource(
                site[3],
                http_retries=1,
                http_delay=0,
                http_timeout=WEB_APP_CHECK_TIMEOUT_SECONDS,
            )
            agent_results = await check_with_agents(
                site[3],
                checks=["http", "ssl", "domain"],
                timeout_sec=WEB_APP_AGENT_TIMEOUT_SECONDS,
            )
            status = format_status_text(
                result.http,
                result.ssl_days,
                result.domain_days,
                result.registrar,
                result.contact_url,
            )
            status = append_agent_results(status, agent_results)
            update_site_status_by_id(site[0], status)
            log_user_action(user.id, f"Mini App: checked site {site[3]}", user.username)
        except Exception as exc:
            return _json_error(
                f"Не удалось выполнить проверку: {type(exc).__name__}",
                status=502,
                code="check_failed",
            )

    return web.json_response(
        {"ok": True, "site": _site_payload_for_user(site[0], user.id)}
    )


def setup_webapp_routes(app: web.Application) -> None:
    if not WEB_APP_ENABLED:
        return
    app.router.add_get("/app", app_redirect)
    app.router.add_get("/app/", app_index)
    app.router.add_static("/app/static/", STATIC_DIR, show_index=False)
    app.router.add_get("/api/webapp/bootstrap", bootstrap)
    app.router.add_post("/api/webapp/feedback/start", start_feedback)
    app.router.add_post("/api/webapp/sites", create_site)
    app.router.add_post("/api/webapp/sites/{site_id:\\d+}/check", check_site)
    app.router.add_post("/api/webapp/sites/{site_id:\\d+}/pause", pause_site)
    app.router.add_post("/api/webapp/sites/{site_id:\\d+}/resume", resume_site)
    app.router.add_post("/api/webapp/sites/{site_id:\\d+}/group", update_site_group)
    app.router.add_get("/api/webapp/sites/{site_id:\\d+}/history", site_history)
    app.router.add_delete("/api/webapp/sites/{site_id:\\d+}", delete_site)
