"""
RANUK BIOSPAN 5.0 — Autonomous Healthspan and AI Longevity Server (aiohttp).
"""
import asyncio
import json
import os
from pathlib import Path
from aiohttp import web

from .collectors.biospan_health import (
    get_whoop_dashboard,
    ask_whoop_coach,
    ingest_wearable_payload,
    toggle_journal_factor,
)
from .collectors.xiaomi_cloud import (
    get_xiaomi_status,
    start_qr_login,
    poll_qr_login,
    start_password_login,
    submit_2fa_code,
    submit_captcha_code,
    login_with_raw_tokens,
    sync_xiaomi_cloud_history,
)

BASE_DIR = Path(__file__).parent
STATIC_DIR = BASE_DIR / "static"


async def index_page(_request):
    return web.FileResponse(STATIC_DIR / "index.html")


async def logo_img(_request):
    logo_path = STATIC_DIR / "logo.png"
    if logo_path.exists():
        return web.FileResponse(logo_path)
    return web.Response(status=404)


async def api_dashboard(_request):
    data = await asyncio.to_thread(get_whoop_dashboard)
    return web.json_response(data)


async def api_coach(request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    msg = str(body.get("message") or "¿Cómo está mi recuperación hoy?")
    res = await asyncio.to_thread(ask_whoop_coach, msg)
    return web.json_response(res)


async def api_journal(request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    fid = str(body.get("factor_id") or "")
    active = bool(body.get("active", True))
    res = await asyncio.to_thread(toggle_journal_factor, fid, active)
    return web.json_response(res)


async def api_webhook(request):
    body = {}
    if request.method == "POST":
        try:
            body = await request.json()
        except Exception:
            try:
                body = dict(await request.post())
            except Exception:
                body = {}
    if not body and request.query:
        body = dict(request.query)

    if request.method == "GET" and not any(k in body for k in ("rhr", "sleep_hours", "steps", "hrv_ms", "spo2")):
        accept = (request.headers.get("Accept") or "").lower()
        if "text/html" in accept:
            raise web.HTTPFound("/?connect=1")
        return web.json_response({
            "ok": True,
            "status": "ready",
            "message": "Ranuk BioSpan Webhook activo.",
            "xiaomi_cloud": await asyncio.to_thread(get_xiaomi_status),
        })

    res = await asyncio.to_thread(ingest_wearable_payload, body)
    return web.json_response(res)


async def api_sync(request):
    days = 35
    try:
        if request.method == "POST":
            b = await request.json()
            days = int(b.get("days", 35))
        elif "days" in request.query:
            days = int(request.query["days"])
    except Exception:
        days = 35

    st = await asyncio.to_thread(get_xiaomi_status)
    sync_res = None
    if st.get("connected"):
        sync_res = await asyncio.to_thread(sync_xiaomi_cloud_history, days)
    data = await asyncio.to_thread(get_whoop_dashboard)
    if sync_res is not None:
        data["sync_result"] = sync_res
    return web.json_response(data)


async def api_xiaomi_status(_request):
    st = await asyncio.to_thread(get_xiaomi_status)
    return web.json_response({"ok": True, **st})


async def api_xiaomi_qr_start(request):
    region = request.query.get("region", "us")
    if request.method == "POST":
        try:
            b = await request.json()
            region = b.get("region", region)
        except Exception:
            pass
    res = await asyncio.to_thread(start_qr_login, region)
    return web.json_response(res)


async def api_xiaomi_qr_poll(request):
    token = request.query.get("token", "")
    if not token and request.method == "POST":
        try:
            b = await request.json()
            token = b.get("token", "")
        except Exception:
            pass
    res = await asyncio.to_thread(poll_qr_login, token)
    return web.json_response(res)


async def api_xiaomi_login(request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    username = str(body.get("username") or "").strip()
    password = str(body.get("password") or "")
    region = str(body.get("region") or "us").strip()
    res = await asyncio.to_thread(start_password_login, username, password, region)
    return web.json_response(res)


async def api_xiaomi_2fa(request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    session_id = str(body.get("session_id") or "").strip()
    otp_code = str(body.get("otp_code") or body.get("code") or "").strip()
    res = await asyncio.to_thread(submit_2fa_code, session_id, otp_code)
    return web.json_response(res)


async def api_xiaomi_captcha(request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    session_id = str(body.get("session_id") or "").strip()
    captcha_code = str(body.get("captcha_code") or body.get("code") or "").strip()
    res = await asyncio.to_thread(submit_captcha_code, session_id, captcha_code)
    return web.json_response(res)


async def api_xiaomi_tokens(request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    res = await asyncio.to_thread(
        login_with_raw_tokens,
        str(body.get("user_id") or ""),
        str(body.get("pass_token") or ""),
        str(body.get("ssecurity") or ""),
        str(body.get("service_token") or ""),
        str(body.get("region") or "us"),
    )
    return web.json_response(res)


def create_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/", index_page)
    app.router.add_get("/whoop", index_page)
    app.router.add_get("/logo.png", logo_img)
    app.router.add_get("/api/whoop", api_dashboard)
    app.router.add_post("/api/whoop/coach", api_coach)
    app.router.add_post("/api/whoop/journal", api_journal)
    app.router.add_get("/api/whoop/webhook", api_webhook)
    app.router.add_post("/api/whoop/webhook", api_webhook)
    app.router.add_get("/api/whoop/sync", api_sync)
    app.router.add_post("/api/whoop/sync", api_sync)
    app.router.add_get("/api/whoop/xiaomi/status", api_xiaomi_status)
    app.router.add_get("/api/whoop/xiaomi/qr/start", api_xiaomi_qr_start)
    app.router.add_post("/api/whoop/xiaomi/qr/start", api_xiaomi_qr_start)
    app.router.add_get("/api/whoop/xiaomi/qr/poll", api_xiaomi_qr_poll)
    app.router.add_post("/api/whoop/xiaomi/qr/poll", api_xiaomi_qr_poll)
    app.router.add_post("/api/whoop/xiaomi/login", api_xiaomi_login)
    app.router.add_post("/api/whoop/xiaomi/2fa", api_xiaomi_2fa)
    app.router.add_post("/api/whoop/xiaomi/captcha", api_xiaomi_captcha)
    app.router.add_post("/api/whoop/xiaomi/tokens", api_xiaomi_tokens)
    return app


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8788))
    host = os.environ.get("HOST", "0.0.0.0")
    print(f"🚀 Ranuk BioSpan 5.0 ejecutándose en http://{host}:{port}/")
    web.run_app(create_app(), host=host, port=port)
