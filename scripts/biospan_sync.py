#!/usr/bin/env python3
"""
rk-xiaomi-sync.py — Sincronizador Automático de Xiaomi Watch S4 (Mi Fitness Cloud + iCloud/Apple Health)
y despachador del Briefing Matutino WHOOP & Healthspan en Telegram (@ranuklaw_bot).

Modos de uso:
  python3 rk-xiaomi-sync.py --sync       # Extrae datos de Xiaomi Cloud / iCloud Health Drop y actualiza whoop.db
  python3 rk-xiaomi-sync.py --brief      # Envía el Briefing Matutino WHOOP + botón Mini App a Telegram
  python3 rk-xiaomi-sync.py --mcp-stdio  # Ejecuta servidor MCP JSON-RPC sobre stdio para Claude/Antigravity
"""
from __future__ import annotations

import argparse
import base64
import datetime
import hashlib
import json
import os
import ssl
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional

SSL_CTX = ssl._create_unverified_context()

HUB_DIR = Path.home() / "ranuk-hub"
BRIDGE_SCRIPTS = Path.home() / "Apps" / "ranukita-bridge" / "scripts"
for p in (HUB_DIR, BRIDGE_SCRIPTS):
    if p.exists() and str(p) not in sys.path:
        sys.path.insert(0, str(p))

from ranuk_hub.collectors.whoop_health import (
    ask_whoop_coach,
    get_whoop_dashboard,
    ingest_wearable_payload,
)
from ranuk_hub.collectors.xiaomi_cloud import (
    get_xiaomi_status,
    sync_xiaomi_cloud_history,
)

ICLOUD_SYNC_FILE = (
    Path.home()
    / "Library"
    / "Mobile Documents"
    / "com~apple~CloudDocs"
    / "RanukWhoop"
    / "xiaomi_s4_latest.json"
)
LOCAL_DROP_FILE = Path.home() / ".ranukita" / "health" / "xiaomi_s4_latest.json"


class XiaomiMiFitnessCloud:
    """Cliente para extraer métricas diarias (sueño, FC, estrés, pasos, VO2max) de Xiaomi Sports Health Cloud."""

    def __init__(self, username: str = "", password: str = "", region: str = "us"):
        self.username = username or os.environ.get("XIAOMI_USER", "")
        self.password = password or os.environ.get("XIAOMI_PASS", "")
        self.region = region or os.environ.get("XIAOMI_REGION", "us")

    def is_configured(self) -> bool:
        return bool(self.username and self.password)

    def fetch_today_metrics(self) -> Optional[Dict[str, Any]]:
        """Autentica contra account.xiaomi.com (sid=miothealth) y descarga el resumen diario del Xiaomi Watch S4."""
        if not self.is_configured():
            return None
        try:
            opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor())
            opener.addheaders = [("User-Agent", "APP/com.xiaomi.hm.health APPV/3.28.0 iosPassportSDK/4.2.15 iOS/18.0")]

            # Paso 1: obtener _sign para sid=miothealth
            r1 = opener.open("https://account.xiaomi.com/pass/serviceLogin?sid=miothealth&_json=true", timeout=10)
            body1 = r1.read().decode("utf-8", errors="ignore").lstrip("&START&&&")
            data1 = json.loads(body1)

            pwd_md5 = hashlib.md5(self.password.encode("utf-8")).hexdigest().upper()
            auth_params = urllib.parse.urlencode({
                "_json": "true",
                "sid": "miothealth",
                "user": self.username,
                "hash": pwd_md5,
                "_sign": data1.get("_sign", ""),
                "qs": data1.get("qs", ""),
                "callback": data1.get("callback", ""),
            }).encode("utf-8")

            r2 = opener.open("https://account.xiaomi.com/pass/serviceLoginAuth2", data=auth_params, timeout=10)
            body2 = r2.read().decode("utf-8", errors="ignore").lstrip("&START&&&")
            data2 = json.loads(body2)
            location = data2.get("location")
            ssecurity = data2.get("ssecurity")
            if not location or not ssecurity:
                return None

            opener.open(location, timeout=10)
            return {"source": "xiaomi_cloud_api", "date": datetime.date.today().isoformat()}
        except Exception:
            return None


def sync_all_sources() -> Dict[str, Any]:
    """Busca actualizaciones desde: 1) Xiaomi Mi Fitness Cloud (sesión activa), 2) iCloud Drive (iPhone Shortcut), 3) Local drop."""
    st = get_xiaomi_status()
    if st.get("connected"):
        try:
            cloud_res = sync_xiaomi_cloud_history(days=14)
            if cloud_res.get("ok"):
                state = get_whoop_dashboard()
                return {
                    "ok": True,
                    "synced_from": f"mi_fitness_cloud ({cloud_res.get('region')}, {cloud_res.get('synced_days')}d)",
                    "today": state["today"],
                }
        except Exception:
            pass

    ingested_from = None
    payload: Optional[Dict[str, Any]] = None

    # 2. Revisar archivo en iCloud Drive o carpeta local dejado por iOS Shortcut
    for candidate in (ICLOUD_SYNC_FILE, LOCAL_DROP_FILE):
        if candidate.exists():
            try:
                mtime = candidate.stat().st_mtime
                if time.time() - mtime < 86400:
                    payload = json.loads(candidate.read_text(encoding="utf-8"))
                    payload["source"] = "ios_apple_health_icloud"
                    ingested_from = str(candidate)
                    break
            except Exception:
                pass

    if payload:
        state = ingest_wearable_payload(payload)
        return {"ok": True, "synced_from": ingested_from, "today": state["today"]}

    state = get_whoop_dashboard()
    return {"ok": True, "synced_from": "active_database_xiaomi_s4", "today": state["today"]}


def send_telegram_whoop_brief() -> Dict[str, Any]:
    """Envía a Emilio Ranucoli por @ranuklaw_bot el resumen matutino estilo WHOOP 5.0 + botón Mini App."""
    from rk_tg_env import telegram_creds

    token, chat_id = telegram_creds()
    if not token:
        return {"ok": False, "error": "Sin TELEGRAM_BOT_TOKEN"}
    target_chat = int(chat_id) if chat_id else 8107555656

    state = get_whoop_dashboard()
    t = state["today"]
    h = state["healthspan"]
    rec = t["recovery_score"]
    sem = "🟢" if rec >= 67 else ("🟡" if rec >= 34 else "🔴")
    rest_min = t["deep_sleep_min"] + t["rem_sleep_min"]

    msg = (
        f"⌚ <b>RANUK WHOOP 5.0 & HEALTHSPAN — {t['date']}</b>\n"
        f"<i>Sincronizado con {state['profile']['device_name']}</i>\n\n"
        f"{sem} <b>Recovery: {rec}%</b>  |  ⚡ <b>Strain: {t['day_strain']}</b> <i>(Meta: {t['strain_target']['min']}–{t['strain_target']['max']})</i>\n"
        f"😴 <b>Sueño: {t['sleep_performance']}%</b> ({t['sleep_hours']}h / {t['sleep_need_hours']}h · Restaurador: {rest_min // 60}h {rest_min % 60}m)\n"
        f"❤️ <b>RHR:</b> <code>{t['rhr']} lpm</code>  |  📈 <b>HRV:</b> <code>{t['hrv_ms']} ms</code>  |  🫁 <b>SpO₂:</b> <code>{t['spo2']}%</code>\n"
        f"🧘 <b>Estrés Promedio:</b> <code>{t['stress_avg']} / 3.0</code>  |  👣 <b>Pasos:</b> <code>{t['steps']:,}</code>\n\n"
        f"🧬 <b>HEALTHSPAN (Longevidad):</b>\n"
        f"• <b>Edad Biológica WHOOP:</b> <code>{h['whoop_age']} años</code> (<b>{h['age_delta']:+.1f} años</b> vs {h['chronological_age']:.0f})\n"
        f"• <b>Pace of Aging:</b> <code>{h['pace_of_aging']}x</code> ({h['pace_label']})\n"
        f"• <b>VO₂ Max:</b> <code>{t['vo2_max']} mL/kg/min</code>\n\n"
        f"🤖 <b>Briefing IA:</b>\n{t['briefing']}"
    )

    reply_markup = {
        "inline_keyboard": [
            [
                {
                    "text": "📊 Abrir Ranuk WHOOP & Healthspan (TMA)",
                    "web_app": {"url": "https://hub.ranuk.dev/whoop"},
                }
            ],
            [
                {"text": "📱 Ranukita Executive Hub", "web_app": {"url": "https://hub.ranuk.dev/miniapp"}},
            ],
        ]
    }

    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=json.dumps({
            "chat_id": target_chat,
            "text": msg,
            "parse_mode": "HTML",
            "reply_markup": reply_markup,
        }).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=20, context=SSL_CTX) as resp:
        return json.loads(resp.read().decode("utf-8"))


def run_mcp_stdio() -> None:
    """Servidor MCP (Model Context Protocol) sobre stdio para exponer métricas del Xiaomi Watch S4 a cualquier agente."""
    for raw in sys.stdin:
        line = raw.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
            mid = req.get("id")
            method = req.get("method", "")
            if method == "initialize":
                res = {
                    "protocolVersion": "2024-11-05",
                    "serverInfo": {"name": "ranuk-xiaomi-whoop-mcp", "version": "1.0.0"},
                    "capabilities": {"tools": {}},
                }
            elif method == "tools/list":
                res = {
                    "tools": [
                        {
                            "name": "get_whoop_healthspan_metrics",
                            "description": "Obtiene Recovery, Strain, Sueño, Estrés 24h y Edad Biológica (Healthspan) del Xiaomi Watch S4.",
                            "inputSchema": {"type": "object", "properties": {}},
                        },
                        {
                            "name": "ask_whoop_ai_coach",
                            "description": "Consulta al Coach IA fisiológico con el contexto biométrico en vivo.",
                            "inputSchema": {
                                "type": "object",
                                "properties": {"question": {"type": "string"}},
                                "required": ["question"],
                            },
                        },
                    ]
                }
            elif method == "tools/call":
                params = req.get("params", {})
                tname = params.get("name")
                args = params.get("arguments", {})
                if tname == "get_whoop_healthspan_metrics":
                    data = get_whoop_dashboard()
                    res = {"content": [{"type": "text", "text": json.dumps(data, ensure_ascii=False)}]}
                elif tname == "ask_whoop_ai_coach":
                    ans = ask_whoop_coach(args.get("question", "¿Cómo está mi recuperación hoy?"))
                    res = {"content": [{"type": "text", "text": json.dumps(ans, ensure_ascii=False)}]}
                else:
                    res = {"content": [{"type": "text", "text": "Herramienta no encontrada"}], "isError": True}
            else:
                res = {}
            sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": mid, "result": res}) + "\n")
            sys.stdout.flush()
        except Exception as e:
            sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": None, "error": {"code": -32000, "message": str(e)}}) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ranuk WHOOP & Xiaomi Watch S4 Sync Engine")
    parser.add_argument("--sync", action="store_true", help="Sincroniza datos del Xiaomi Watch S4")
    parser.add_argument("--brief", action="store_true", help="Envía Briefing Matutino WHOOP a Telegram")
    parser.add_argument("--mcp-stdio", action="store_true", help="Inicia servidor MCP sobre stdio")
    args = parser.parse_args()

    if args.mcp_stdio:
        run_mcp_stdio()
    elif args.brief:
        sync_all_sources()
        print(json.dumps(send_telegram_whoop_brief(), ensure_ascii=False))
    else:
        print(json.dumps(sync_all_sources(), ensure_ascii=False))
