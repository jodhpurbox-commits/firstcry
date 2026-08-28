"""
Meesho Number + OTP Telegram Bot (High-Speed Render 24/7 Cloud Service)
------------------------------------------------------------------------
Interactive 1-Tap Workflow:
1. User taps "📱 Get Fresh Number" (or /get).
2. Bot auto-rents from GrizzlySMS (service='hp', country=22) and checks Meesho registration.
3. If registered -> immediately queues the number into the 2-Minute Background Auto-Refund Queue so 100% of the balance is refunded by Grizzly.
4. If unregistered -> sends a NEW notification message with the clean 10-digit number.
5. Bot continuously polls GrizzlySMS site (every 1.5s) for the incoming OTP.
6. If no OTP is received within 2 minutes (120s) -> automatically cancels activation on Grizzly for full refund.
7. As soon as the OTP is received on the site, bot immediately sends the OTP code to Telegram!
"""

import http.server
import json
import logging
import os
import re
import socketserver
import sys
import threading
import time
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

try:
    import telebot
    from telebot import types
except ImportError:
    print("Error: pyTelegramBotAPI is required. Please run: pip install pyTelegramBotAPI requests")
    sys.exit(1)

# Ensure UTF-8 stdout across Windows consoles
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s")
logger = logging.getLogger("MeeshoBot")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "meeshoshop_bot.json")

PORT = int(os.environ.get("PORT", 10000))
RENDER_EXTERNAL_URL = os.environ.get("RENDER_EXTERNAL_URL", "")

GRIZZLY_BASE = os.environ.get("GRIZZLY_BASE_URL", "https://api.grizzlysms.com/stubs/handler_api.php")
MEESHO_CHECK = os.environ.get("MEESHO_CHECK_URL", "https://meeshoshop.94.136.188.137.nip.io/api/public/number-check")
DEFAULT_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "8709329900:AAFyAgNOqZRCzEUhTI1jEP3EyWcNMECPDjc")
DEFAULT_GRIZZLY_KEY = os.environ.get("GRIZZLY_API_KEY", "804def05f9fa4a8469bf9704f1edfa73")

# Persistent, high-concurrency HTTP session with connection pooling
HTTP_SESSION = requests.Session()
retries = Retry(total=2, backoff_factor=0.2, status_forcelist=[500, 502, 503, 504])
adapter = HTTPAdapter(pool_connections=50, pool_maxsize=50, max_retries=retries)
HTTP_SESSION.mount("https://", adapter)
HTTP_SESSION.mount("http://", adapter)

# Country code and Service code resolution maps for GrizzlySMS API
COUNTRY_MAP: Dict[str, int] = {
    "india": 22,
    "in": 22,
    "russia": 0,
    "ru": 0,
    "usa": 187,
    "us": 187,
    "indonesia": 6,
    "id": 6,
    "philippines": 4,
    "ph": 4,
    "vietnam": 10,
    "vn": 10,
}

SERVICE_MAP: Dict[str, str] = {
    "meesho": "hp",
    "meeshoshop": "hp",
    "hp": "hp",
    "swiggy": "cw",
    "whatsapp": "wa",
    "telegram": "tg",
}


def resolve_country(val: Any) -> int:
    if isinstance(val, int):
        return val
    s = str(val).strip().lower()
    if s.isdigit():
        return int(s)
    return COUNTRY_MAP.get(s, 22)


def resolve_service(val: Any) -> str:
    s = str(val).strip().lower()
    return SERVICE_MAP.get(s, s)


DEFAULT_CONFIG: Dict[str, Any] = {
    "bot_token": DEFAULT_BOT_TOKEN,
    "allowed_users": [],
    "grizzly_api_key": DEFAULT_GRIZZLY_KEY,
    "grizzly_base": GRIZZLY_BASE,
    "meesho_check": MEESHO_CHECK,
    "service": "hp",
    "country": 22,
    "max_price": "",
    "poll_interval": 1.5,
    "otp_timeout": 120,
    "workers": 4,
}


def load_config() -> Dict[str, Any]:
    cfg = dict(DEFAULT_CONFIG)
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
                cfg.update(json.load(fh))
        except Exception as e:
            logger.warning(f"Failed to load {CONFIG_PATH}: {e}")

    # Environment variable overrides
    if os.environ.get("TELEGRAM_BOT_TOKEN"):
        cfg["bot_token"] = os.environ["TELEGRAM_BOT_TOKEN"]
    if os.environ.get("GRIZZLY_API_KEY"):
        cfg["grizzly_api_key"] = os.environ["GRIZZLY_API_KEY"]
    if os.environ.get("MEESHO_CHECK_URL"):
        cfg["meesho_check"] = os.environ["MEESHO_CHECK_URL"]
    return cfg


def save_config(cfg: Dict[str, Any]) -> None:
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as fh:
            json.dump(cfg, fh, indent=2)
    except Exception as e:
        logger.error(f"Failed to save {CONFIG_PATH}: {e}")


CFG = load_config()

# Global reference to telebot instance
BOT_INSTANCE: Optional[telebot.TeleBot] = None

# Track active user sessions for live interactive flow
# chat_id -> {"aid": aid, "phone": phone, "stop_event": Event, "status": str}
ACTIVE_SESSIONS: Dict[int, Dict[str, Any]] = {}
SESSIONS_LOCK = threading.Lock()

# Background Auto-Refund Queue for activations to be cancelled at the 2-minute mark
AUTO_REFUND_QUEUE: List[Dict[str, Any]] = []
REFUND_LOCK = threading.Lock()


def queue_for_refund(aid: str, phone: str, rent_time: Optional[float] = None) -> None:
    """Adds a rented number to the background queue to cancel after 2 minutes for 100% refund."""
    with REFUND_LOCK:
        # Avoid duplicate queue entries
        if not any(item["aid"] == aid for item in AUTO_REFUND_QUEUE):
            AUTO_REFUND_QUEUE.append({
                "aid": aid,
                "phone": phone,
                "rent_time": rent_time or time.time(),
                "attempts": 0,
            })
    logger.info(f"💰 [Auto-Refund Queue] Queued +{phone} (AID: {aid}) to cancel at 2 min for 100% refund.")


def is_authorized(chat_id: int, cfg: Dict[str, Any]) -> bool:
    allowed = cfg.get("allowed_users") or []
    if not allowed:
        return True
    return chat_id in [int(u) for u in allowed]


def get_main_keyboard() -> types.ReplyKeyboardMarkup:
    """Returns persistent 1-tap quick action keyboard for mobile users."""
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    btn_get = types.KeyboardButton("📱 Get Fresh Number")
    btn_next = types.KeyboardButton("🔄 Next Number")
    btn_bal = types.KeyboardButton("💳 Balance")
    btn_cancel = types.KeyboardButton("🛑 Cancel")
    kb.add(btn_get, btn_next)
    kb.add(btn_bal, btn_cancel)
    return kb


def safe_send_message(
    bot: telebot.TeleBot,
    chat_id: int,
    text: str,
    reply_markup: Optional[Any] = None,
    parse_mode: Optional[str] = "Markdown",
) -> Optional[Any]:
    """Sends a Telegram message with automatic fallback to avoid formatting errors."""
    try:
        return bot.send_message(chat_id, text, reply_markup=reply_markup, parse_mode=parse_mode, timeout=10)
    except Exception:
        try:
            return bot.send_message(chat_id, text, reply_markup=reply_markup, timeout=10)
        except Exception as err:
            logger.error(f"Error sending message to {chat_id}: {err}")
            return None


def safe_delete_message(bot: telebot.TeleBot, chat_id: int, message_id: int) -> None:
    """Safely deletes a temporary message."""
    try:
        bot.delete_message(chat_id=chat_id, message_id=message_id, timeout=5)
    except Exception:
        pass


# ---------------- High-Speed GrizzlySMS Integration ----------------
def grizzly(cfg: Dict[str, Any], action: str, **params: Any) -> str:
    cleaned = {k: v for k, v in params.items() if v not in (None, "")}
    cleaned["api_key"] = cfg["grizzly_api_key"]
    cleaned["action"] = action
    try:
        r = HTTP_SESSION.get(cfg["grizzly_base"], params=cleaned, timeout=12)
        return r.text.strip()
    except Exception as e:
        logger.error(f"GrizzlySMS API Error ({action}): {e}")
        return f"ERROR:{e}"


def g_balance(cfg: Dict[str, Any]) -> str:
    return grizzly(cfg, "getBalance")


def g_get_number(cfg: Dict[str, Any]) -> Tuple[Optional[str], str]:
    service_code = resolve_service(cfg.get("service", "hp"))
    country_id = resolve_country(cfg.get("country", 22))

    txt = grizzly(
        cfg,
        "getNumber",
        service=service_code,
        country=country_id,
        maxPrice=cfg.get("max_price", ""),
    )
    if txt.startswith("ACCESS_NUMBER"):
        parts = txt.split(":", 2)
        if len(parts) == 3:
            return parts[1].strip(), parts[2].strip()
    return None, txt


def g_status(cfg: Dict[str, Any], aid: str) -> str:
    return grizzly(cfg, "getStatus", id=aid)


def g_cancel(cfg: Dict[str, Any], aid: str) -> str:
    """Cancels activation on GrizzlySMS (action=setStatus&status=8)."""
    return grizzly(cfg, "setStatus", status=8, id=aid)


def g_finish(cfg: Dict[str, Any], aid: str) -> str:
    """Completes activation on GrizzlySMS (action=setStatus&status=6)."""
    return grizzly(cfg, "setStatus", status=6, id=aid)


# ---------------- Background Auto-Refund Worker ----------------
def auto_refund_worker(cfg: Dict[str, Any]) -> None:
    """
    Background worker that runs continuously.
    Cancels activations on GrizzlySMS once they reach 125 seconds (~2 minutes),
    ensuring 100% of the funds are refunded to the account balance.
    """
    logger.info("Auto-Refund Background Worker started (2-minute refund queue active).")
    while True:
        try:
            now = time.time()
            with REFUND_LOCK:
                items_to_process = list(AUTO_REFUND_QUEUE)

            for item in items_to_process:
                age = now - item["rent_time"]
                # Wait until activation is at least 125 seconds old (2 min + 5s buffer)
                if age >= 125:
                    aid = item["aid"]
                    phone = item["phone"]
                    res = g_cancel(cfg, aid)
                    logger.info(f"💸 [Auto-Refund] Cancel status for +{phone} (AID {aid}, age {age:.0f}s): {res}")

                    if "ACCESS_CANCEL" in res or "CANCEL" in res or "EARLY_CANCEL_DENIED" not in res:
                        with REFUND_LOCK:
                            if item in AUTO_REFUND_QUEUE:
                                AUTO_REFUND_QUEUE.remove(item)
                        logger.info(f"✅ [Auto-Refund SUCCESS] Number +{phone} (AID: {aid}) cancelled & refunded!")
                    else:
                        item["attempts"] += 1
                        if item["attempts"] > 10:
                            with REFUND_LOCK:
                                if item in AUTO_REFUND_QUEUE:
                                    AUTO_REFUND_QUEUE.remove(item)
        except Exception as e:
            logger.error(f"Error in auto_refund_worker: {e}")

        time.sleep(10)


# ---------------- Meesho Registration Check ----------------
def to_ten_digit(phone: str) -> str:
    digits = re.sub(r"\D", "", str(phone))
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    if len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    return digits


def is_registered(cfg: Dict[str, Any], phone: str) -> Tuple[Optional[bool], Any]:
    ten = to_ten_digit(phone)
    if len(ten) != 10:
        return None, f"bad_phone:{phone}"
    try:
        r = HTTP_SESSION.get(cfg["meesho_check"], params={"number": ten}, timeout=12)
        d = r.json()
    except Exception as e:
        logger.error(f"Meesho check network error ({ten}): {e}")
        return None, f"check_err:{e}"

    if "registered" in d:
        return bool(d["registered"]), d
    if d.get("ok") is True and "registered" not in d:
        return False, d
    if d.get("error") == "invalid_number":
        return None, "invalid_number"
    return None, d


def extract_otp_code(raw_status: str) -> Tuple[str, Optional[str]]:
    """Extracts numeric 4-6 digit OTP code and optional SMS description."""
    payload = raw_status
    if ":" in raw_status:
        parts = raw_status.split(":", 1)
        payload = parts[1].strip()

    # Search for standard 4, 5, or 6 digit OTP numbers
    matches = re.findall(r"\b\d{4,6}\b", payload)
    if matches:
        otp_code = matches[-1]
        desc = payload if (payload != otp_code and len(payload) > 6) else None
        return otp_code, desc
    return payload, None


# ---------------- Interactive Single-Number Flow ----------------
def cancel_active_session(chat_id: int, cfg: Dict[str, Any], notify_user: bool = False, bot: Optional[telebot.TeleBot] = None) -> None:
    """Cancels and cleans up any currently running session for this chat and queues for refund."""
    with SESSIONS_LOCK:
        sess = ACTIVE_SESSIONS.pop(chat_id, None)

    if sess:
        sess["stop_event"].set()
        aid = sess.get("aid")
        phone = sess.get("phone")
        rent_time = sess.get("rent_time", time.time())
        if aid:
            age = time.time() - rent_time
            if age >= 125:
                g_cancel(cfg, aid)
                logger.info(f"Immediately cancelled Grizzly activation {aid} (+{phone}) for chat {chat_id}")
            else:
                queue_for_refund(aid, phone, rent_time)

        if notify_user and bot:
            safe_send_message(bot, chat_id, f"🛑 Activation for `+{phone}` released.\n💰 Auto-refund scheduled in 2 min.", reply_markup=get_main_keyboard())


def hunt_and_wait_for_otp(bot: telebot.TeleBot, chat_id: int, cfg: Dict[str, Any], status_msg_id: Optional[int] = None) -> None:
    """
    Rents numbers until an UNREGISTERED one is found, delivers it to the user in a NEW message,
    and then continuously waits for the OTP to arrive from the site.
    Auto-cancels and auto-refunds if no OTP arrives within 2 minutes.
    """
    stop_event = threading.Event()
    with SESSIONS_LOCK:
        ACTIVE_SESSIONS[chat_id] = {
            "aid": None,
            "phone": None,
            "stop_event": stop_event,
            "status": "HUNTING",
            "rent_time": time.time(),
        }

    attempt = 0
    max_attempts = 25
    found_aid = None
    found_phone = None
    rent_timestamp = None

    while not stop_event.is_set() and attempt < max_attempts:
        attempt += 1
        logger.info(f"[Chat {chat_id}] Hunt attempt #{attempt}: Renting from Grizzly (service={resolve_service(cfg.get('service', 'hp'))}, country={resolve_country(cfg.get('country', 22))})...")

        aid, info = g_get_number(cfg)
        now_time = time.time()
        if not aid:
            logger.warning(f"Grizzly getNumber error: {info}")
            if "NO_NUMBERS" in info or "NO_BALANCE" in info or "BAD_KEY" in info:
                msg = f"⚠️ *Grizzly Notice*: `{info}`\nPlease check `/balance` or try again shortly."
                safe_send_message(bot, chat_id, msg, reply_markup=get_main_keyboard())
                with SESSIONS_LOCK:
                    ACTIVE_SESSIONS.pop(chat_id, None)
                return
            time.sleep(1.5)
            continue

        # Check Meesho registration
        reg, raw = is_registered(cfg, info)
        if reg is True:
            # Already registered on Meesho -> queue for automatic refund at 2 minutes
            logger.info(f"🚫 +{info} is REGISTERED on Meesho -> Queuing for 2-min auto-refund...")
            queue_for_refund(aid, info, now_time)
            continue

        if reg is None:
            # Inconclusive / bad number -> queue for refund
            logger.warning(f"❓ +{info} check inconclusive ({raw}) -> Queuing for refund...")
            queue_for_refund(aid, info, now_time)
            continue

        # Found fresh unregistered number!
        found_aid = aid
        found_phone = info
        rent_timestamp = now_time
        break

    # Clean up the temporary searching message
    if status_msg_id:
        safe_delete_message(bot, chat_id, status_msg_id)

    if stop_event.is_set():
        if found_aid:
            queue_for_refund(found_aid, found_phone, rent_timestamp)
        with SESSIONS_LOCK:
            ACTIVE_SESSIONS.pop(chat_id, None)
        return

    if not found_aid or not found_phone:
        msg = "⚠️ Could not find an unregistered number after multiple attempts. Tap below to try again."
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("🔄 Try Again", callback_data="get_new"))
        safe_send_message(bot, chat_id, msg, reply_markup=kb)
        with SESSIONS_LOCK:
            ACTIVE_SESSIONS.pop(chat_id, None)
        return

    # Update session state with the confirmed unregistered number
    with SESSIONS_LOCK:
        if chat_id in ACTIVE_SESSIONS:
            ACTIVE_SESSIONS[chat_id]["aid"] = found_aid
            ACTIVE_SESSIONS[chat_id]["phone"] = found_phone
            ACTIVE_SESSIONS[chat_id]["status"] = "WAITING_OTP"
            ACTIVE_SESSIONS[chat_id]["rent_time"] = rent_timestamp or time.time()

    ten_digit = to_ten_digit(found_phone)
    formatted = f"+{found_phone}"

    logger.info(f"✨ Fresh unregistered number delivered to Chat {chat_id}: {formatted} (10-digit: {ten_digit})")

    # Interactive action buttons
    kb = types.InlineKeyboardMarkup(row_width=2)
    btn_cancel = types.InlineKeyboardButton("❌ Cancel / Refund", callback_data=f"cancel_{found_aid}")
    btn_next = types.InlineKeyboardButton("🔄 Next Number", callback_data="get_new")
    kb.add(btn_cancel, btn_next)

    number_card = (
        "✨ *FRESH UNREGISTERED MEESHO NUMBER* ✨\n"
        "====================================\n"
        "📱 *10-Digit Phone (Tap to copy)*:\n"
        f"`{ten_digit}`\n\n"
        "📱 *Full Number*:\n"
        f"`{formatted}`\n"
        "====================================\n"
        "👉 *Enter this number in Meesho now & request OTP!*\n"
        "⏳ *Waiting for OTP code...* (Auto-cancels for full refund after 2 mins if no OTP)"
    )

    # ALWAYS send a fresh new message so it pops up with notification sound and banner!
    safe_send_message(bot, chat_id, number_card, reply_markup=kb)

    # ---------------- OTP Polling Loop (2-Minute Timeout) ----------------
    otp_timeout_secs = int(cfg.get("otp_timeout", 120))  # 2 Minutes
    deadline = time.time() + otp_timeout_secs
    poll_interval = max(1.0, float(cfg.get("poll_interval", 1.5)))
    got_otp = None
    sms_desc = None

    while time.time() < deadline and not stop_event.is_set():
        st = g_status(cfg, found_aid)
        if st.startswith("ACCESS_OK") or st.startswith("STATUS_OK"):
            got_otp, sms_desc = extract_otp_code(st)
            break
        if st.startswith("ACCESS_CANCEL") or st.startswith("CANCEL") or st.startswith("ACCESS_FAULT"):
            break
        time.sleep(poll_interval)

    with SESSIONS_LOCK:
        ACTIVE_SESSIONS.pop(chat_id, None)

    if stop_event.is_set():
        return

    if got_otp:
        logger.info(f"🎉 OTP Received on site for {formatted}: {got_otp}")
        # Mark activation finished on Grizzly
        g_finish(cfg, found_aid)

        done_kb = types.InlineKeyboardMarkup(row_width=2)
        done_kb.add(
            types.InlineKeyboardButton("📱 Get Next Number", callback_data="get_new"),
            types.InlineKeyboardButton("💳 Check Balance", callback_data="check_bal"),
        )
        otp_msg = (
            "🎉 *MEESHO OTP RECEIVED FROM SITE!* 🎉\n"
            "====================================\n"
            f"📱 *Phone*: `{formatted}`\n"
            f"🔢 *OTP Code (Tap to copy)*:\n"
            f"`{got_otp}`\n"
            "====================================\n"
        )
        if sms_desc:
            otp_msg += f"💬 *SMS*: _{sms_desc}_\n"
        otp_msg += "✅ Ready! Tap below to get your next number:"

        safe_send_message(bot, chat_id, otp_msg, reply_markup=done_kb)
    else:
        # Timeout without OTP -> Auto-cancel on Grizzly for 100% refund
        res = g_cancel(cfg, found_aid)
        logger.info(f"⏳ 2-minute timeout for {formatted} -> Cancelled on Grizzly: {res}")
        if "EARLY_CANCEL_DENIED" in res:
            queue_for_refund(found_aid, found_phone, rent_timestamp)

        timeout_kb = types.InlineKeyboardMarkup(row_width=2)
        timeout_kb.add(
            types.InlineKeyboardButton("📱 Get Fresh Number", callback_data="get_new"),
            types.InlineKeyboardButton("💳 Check Balance", callback_data="check_bal"),
        )
        safe_send_message(
            bot,
            chat_id,
            f"⏳ *2 Minutes Expired for `{formatted}` (no OTP received)*.\n"
            "💰 *Activation cancelled on GrizzlySMS — balance refunded 100%!*",
            reply_markup=timeout_kb,
        )


# ---------------- HTTP Healthcheck & External OTP Webhook Server ----------------
class HealthCheckHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlsplit(self.path).path
        if parsed in ("/", "/healthz", "/ping", "/status"):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            status_payload = {
                "status": "ok",
                "service": "Meesho Number + OTP Bot (High-Speed)",
                "uptime": "24/7",
                "active_sessions": len(ACTIVE_SESSIONS),
                "refund_queue_size": len(AUTO_REFUND_QUEUE),
                "otp_webhook_endpoint": "/api/otp",
            }
            self.wfile.write(json.dumps(status_payload, indent=2).encode("utf-8"))
            return
        self.send_response(404)
        self.end_headers()

    def do_POST(self):
        """
        Receives OTP directly from external sites, scripts, or webhooks.
        Endpoint: POST /api/otp or POST /webhook/otp
        Payload: {"phone": "9876543210", "otp": "123456", "message": "..."}
        """
        parsed = urllib.parse.urlsplit(self.path).path
        if parsed in ("/api/otp", "/webhook/otp", "/push_otp", "/otp"):
            length = int(self.headers.get("Content-Length", 0))
            body_bytes = self.rfile.read(length)
            try:
                data = json.loads(body_bytes.decode("utf-8"))
                phone = data.get("number") or data.get("phone") or ""
                otp_code = str(data.get("otp") or data.get("code") or "")
                sms_text = data.get("message") or data.get("text") or ""
                target_chat_id = data.get("chat_id")

                if not otp_code:
                    self.send_response(400)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(b'{"ok":false,"error":"Missing otp/code field"}')
                    return

                logger.info(f"Incoming OTP from site API for {phone}: {otp_code}")

                # Locate matching active chat session
                delivered_to = []
                with SESSIONS_LOCK:
                    for cid, sess in list(ACTIVE_SESSIONS.items()):
                        sess_phone = sess.get("phone", "")
                        if not phone or (to_ten_digit(phone) == to_ten_digit(sess_phone)) or target_chat_id == cid:
                            sess["stop_event"].set()
                            delivered_to.append(cid)

                # Send Telegram message instantly
                if BOT_INSTANCE:
                    recipients = delivered_to or ([int(target_chat_id)] if target_chat_id else list(ACTIVE_SESSIONS.keys()))
                    for cid in recipients:
                        if cid:
                            otp_msg = (
                                "🎉 *MEESHO OTP RECEIVED (VIA SITE WEBHOOK)!* 🎉\n"
                                "====================================\n"
                                f"📱 *Phone*: `+{phone or 'Active Number'}`\n"
                                f"🔢 *OTP Code (Tap to copy)*:\n"
                                f"`{otp_code}`\n"
                                "====================================\n"
                            )
                            if sms_text:
                                otp_msg += f"💬 *SMS*: _{sms_text}_\n"

                            done_kb = types.InlineKeyboardMarkup(row_width=2)
                            done_kb.add(
                                types.InlineKeyboardButton("📱 Get Next Number", callback_data="get_new"),
                                types.InlineKeyboardButton("💳 Check Balance", callback_data="check_bal"),
                            )
                            safe_send_message(BOT_INSTANCE, cid, otp_msg, reply_markup=done_kb)

                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"ok": True, "delivered_to": delivered_to, "otp": otp_code}).encode("utf-8"))
                return
            except Exception as e:
                logger.error(f"Error handling /api/otp POST: {e}")
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"ok": False, "error": str(e)}).encode("utf-8"))
                return

        self.send_response(404)
        self.end_headers()

    def log_message(self, format, *args):
        pass


def run_http_server():
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("", PORT), HealthCheckHandler) as httpd:
        logger.info(f"Healthcheck & OTP Webhook Server listening on 0.0.0.0:{PORT}")
        httpd.serve_forever()


def keep_alive_worker():
    """Periodically self-pings the public URL to keep Render free containers active."""
    time.sleep(30)
    base_url = (RENDER_EXTERNAL_URL or f"http://127.0.0.1:{PORT}").rstrip("/")
    ping_url = f"{base_url}/healthz"

    while True:
        try:
            req = urllib.request.Request(ping_url, headers={"User-Agent": "MeeshoKeepAlive/1.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                logger.debug(f"Keep-alive ping {ping_url} -> HTTP {resp.getcode()}")
        except Exception as e:
            logger.debug(f"Keep-alive notice: {e}")
        time.sleep(600)  # Ping every 10 minutes


# ---------------- Telegram Bot Runner ----------------
def create_bot() -> telebot.TeleBot:
    global BOT_INSTANCE
    cfg = load_config()
    token = cfg.get("bot_token") or DEFAULT_BOT_TOKEN
    if not token or ":" not in token:
        logger.error("Bot token not configured! Set TELEGRAM_BOT_TOKEN in environment or meeshoshop_bot.json.")
        sys.exit(1)

    # Initialize TeleBot with 24 worker threads for instant multi-tasking
    bot = telebot.TeleBot(token, threaded=True, num_threads=24, skip_pending=True)
    BOT_INSTANCE = bot

    def trigger_get_number(chat_id: int):
        cancel_active_session(chat_id, cfg)
        status_msg = safe_send_message(
            bot,
            chat_id,
            "🔍 *Searching GrizzlySMS for a fresh unregistered Meesho number...*",
            reply_markup=get_main_keyboard(),
        )
        msg_id = status_msg.message_id if status_msg else None
        t = threading.Thread(target=hunt_and_wait_for_otp, args=(bot, chat_id, cfg, msg_id), daemon=True)
        t.start()

    @bot.message_handler(commands=["start", "help"])
    def cmd_start(m):
        if not is_authorized(m.chat.id, cfg):
            safe_send_message(bot, m.chat.id, "⛔ Unauthorized.")
            return
        text = (
            "👋 *Welcome to Meesho Number + OTP Assistant!*\n\n"
            "1️⃣ Tap *'📱 Get Fresh Number'* below.\n"
            "2️⃣ The bot automatically finds an *unregistered Meesho number* and sends it to you.\n"
            "3️⃣ Enter the number on Meesho app and request OTP.\n"
            "4️⃣ When the OTP is received on the site, the bot *immediately sends the OTP here*!\n\n"
            "💰 *Auto-Refund Protection*: All registered numbers & numbers with no OTP after 2 min are automatically cancelled on GrizzlySMS for a 100% refund."
        )
        safe_send_message(bot, m.chat.id, text, reply_markup=get_main_keyboard())

    @bot.message_handler(commands=["get", "rent", "number", "scan"])
    def cmd_get(m):
        if not is_authorized(m.chat.id, cfg):
            return
        trigger_get_number(m.chat.id)

    @bot.message_handler(commands=["next"])
    def cmd_next(m):
        if not is_authorized(m.chat.id, cfg):
            return
        trigger_get_number(m.chat.id)

    @bot.message_handler(commands=["cancel"])
    def cmd_cancel(m):
        if not is_authorized(m.chat.id, cfg):
            return
        cancel_active_session(m.chat.id, cfg, notify_user=True, bot=bot)

    @bot.message_handler(commands=["balance"])
    def cmd_balance(m):
        if not is_authorized(m.chat.id, cfg):
            return
        bal = g_balance(cfg)
        safe_send_message(bot, m.chat.id, f"💳 *GrizzlySMS Balance*: `{bal}`", reply_markup=get_main_keyboard())

    @bot.message_handler(commands=["config"])
    def cmd_config(m):
        if not is_authorized(m.chat.id, cfg):
            return
        safe = dict(cfg)
        if safe.get("grizzly_api_key"):
            safe["grizzly_api_key"] = safe["grizzly_api_key"][:6] + "..." + safe["grizzly_api_key"][-4:]
        if safe.get("bot_token"):
            safe["bot_token"] = safe["bot_token"][:8] + "..."
        safe_send_message(bot, m.chat.id, f"⚙️ *Configuration:*\n```json\n{json.dumps(safe, indent=2)}\n```", reply_markup=get_main_keyboard())

    @bot.message_handler(commands=["set"])
    def cmd_set(m):
        if not is_authorized(m.chat.id, cfg):
            return
        parts = (m.text or "").split()
        if len(parts) < 3:
            safe_send_message(bot, m.chat.id, "Usage: `/set <key> <value>`\nExample: `/set otp_timeout 120`", reply_markup=get_main_keyboard())
            return
        key, val = parts[1], parts[2]
        if key in ("service", "country", "max_price", "poll_interval", "otp_timeout", "workers"):
            cfg[key] = val if key in ("service", "country", "max_price") else (int(val) if val.isdigit() else val)
            save_config(cfg)
            safe_send_message(bot, m.chat.id, f"✅ Updated `{key}` = `{cfg[key]}`", reply_markup=get_main_keyboard())
        else:
            safe_send_message(bot, m.chat.id, f"❌ Unknown setting: `{key}`", reply_markup=get_main_keyboard())

    # Text button handler
    @bot.message_handler(func=lambda m: True)
    def handle_text(m):
        if not is_authorized(m.chat.id, cfg):
            return
        text = (m.text or "").strip()
        if text == "📱 Get Fresh Number":
            trigger_get_number(m.chat.id)
        elif text == "🔄 Next Number":
            trigger_get_number(m.chat.id)
        elif text == "💳 Balance":
            bal = g_balance(cfg)
            safe_send_message(bot, m.chat.id, f"💳 *GrizzlySMS Balance*: `{bal}`", reply_markup=get_main_keyboard())
        elif text in ("🛑 Cancel", "❌ Cancel"):
            cancel_active_session(m.chat.id, cfg, notify_user=True, bot=bot)
        else:
            safe_send_message(
                bot,
                m.chat.id,
                "💡 Tap *'📱 Get Fresh Number'* below to get an unregistered Meesho number.",
                reply_markup=get_main_keyboard(),
            )

    # Inline callback queries handler
    @bot.callback_query_handler(func=lambda call: True)
    def handle_callback(call):
        chat_id = call.message.chat.id
        data = call.data or ""
        try:
            bot.answer_callback_query(call.id)
        except Exception:
            pass

        if data == "get_new":
            trigger_get_number(chat_id)
        elif data == "check_bal":
            bal = g_balance(cfg)
            safe_send_message(bot, chat_id, f"💳 *GrizzlySMS Balance*: `{bal}`", reply_markup=get_main_keyboard())
        elif data.startswith("cancel_"):
            aid = data.replace("cancel_", "")
            cancel_active_session(chat_id, cfg, notify_user=True, bot=bot)

    return bot


def main():
    logger.info("=" * 60)
    logger.info("Starting High-Speed Meesho Number + OTP Telegram Bot")
    logger.info("=" * 60)

    cfg = load_config()

    # 1. Start HTTP Healthcheck Server in background daemon thread
    http_thread = threading.Thread(target=run_http_server, daemon=True)
    http_thread.start()

    # 2. Start Keep-Alive Worker in background daemon thread
    ka_thread = threading.Thread(target=keep_alive_worker, daemon=True)
    ka_thread.start()

    # 3. Start 2-Minute Background Auto-Refund Worker
    refund_thread = threading.Thread(target=auto_refund_worker, args=(cfg,), daemon=True)
    refund_thread.start()

    # 4. Give HTTP Server a moment to bind
    time.sleep(1)

    # 5. Initialize Telegram Bot
    bot = create_bot()

    # Remove any old webhook to prevent 409 conflict latency
    try:
        bot.remove_webhook()
    except Exception as e:
        logger.debug(f"Webhook reset notice: {e}")

    # 6. Continuous Polling Loop with auto-reconnection
    logger.info("Entering Telegram Bot Polling Loop (Interactive Flow Active)...")
    while True:
        try:
            bot.infinity_polling(timeout=15, long_polling_timeout=15, restart_on_change=False)
        except Exception as e:
            logger.error(f"Polling loop error: {e}. Reconnecting in 3s...")
            time.sleep(3)


if __name__ == "__main__":
    main()
