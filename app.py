"""
FirstCry Cloud Runner (Render.com / Production)
-----------------------------------------------
Unified Web Service & Telegram Bot Runner:
1. Serves the Telegram Mini App & Static Assets on Render's $PORT (Default: 10000).
2. Runs the Telegram Bot (@firstcry4bot) polling service in a background worker thread.
3. Automatically synchronizes the Telegram Mini App Menu Button with Render's public URL.
"""

import http.server
import logging
import os
import socketserver
import threading
import time
import urllib.request
import json
from typing import Any, Dict

import telegram_bot
from firstcry_client import FirstCryClient

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s")
logger = logging.getLogger("RenderCloudApp")

PORT = int(os.environ.get("PORT", 10000))
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "8709329900:AAFyAgNOqZRCzEUhTI1jEP3EyWcNMECPDjc")
RENDER_EXTERNAL_URL = os.environ.get("RENDER_EXTERNAL_URL", "")

WEBAPP_DIR = os.path.join(os.path.dirname(__file__), "webapp")


class MiniAppHTTPRequestHandler(http.server.SimpleHTTPRequestHandler):
    """HTTP Request Handler to serve Mini App and healthcheck endpoints."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=WEBAPP_DIR, **kwargs)

    def do_GET(self):
        # Strip query parameters so Telegram Mini App query strings don't cause 404s
        parsed_url = urllib.parse.urlsplit(self.path)
        clean_path = parsed_url.path

        # Health check endpoint for Render
        if clean_path in ("/healthz", "/ping", "/status"):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status":"ok","service":"FirstCry Telegram Bot & Mini App"}')
            return

        # Default route to index.html
        if clean_path in ("/", ""):
            self.path = "/index.html"
            if parsed_url.query:
                self.path += f"?{parsed_url.query}"

        return super().do_GET()

    def log_message(self, format, *args):
        # Suppress routine static GET logs to keep Render console clean
        if "/healthz" in (args[0] if args else ""):
            return
        logger.debug(f"{self.address_string()} - {format % args}")


def sync_telegram_menu_button(public_url: str):
    """Sets the Telegram Chat Menu Button to point to Render's public HTTPS URL."""
    if not public_url.startswith("https://"):
        logger.warning(f"Public URL '{public_url}' does not start with https://. Skipping setChatMenuButton.")
        return

    # Save to local file so telegram_bot.py resolves it immediately
    url_file = os.path.join(os.path.dirname(__file__), "miniapp_url.txt")
    try:
        with open(url_file, "w", encoding="utf-8") as f:
            f.write(public_url)
    except Exception as e:
        logger.error(f"Failed to write miniapp_url.txt: {e}")

    # Call Telegram setChatMenuButton API
    api_url = f"https://api.telegram.org/bot{BOT_TOKEN}/setChatMenuButton"
    body = {
        "menu_button": {
            "type": "web_app",
            "text": "Open Mini App",
            "web_app": {"url": public_url}
        }
    }
    try:
        req = urllib.request.Request(
            api_url,
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if data.get("ok"):
                logger.info(f"Successfully configured Telegram Chat Menu Button -> {public_url}")
            else:
                logger.warning(f"Telegram setChatMenuButton returned: {data}")
    except Exception as e:
        logger.error(f"Error syncing Telegram menu button: {e}")


def run_http_server():
    """Starts the static web server for Render."""
    logger.info(f"Starting HTTP Web Server on port {PORT} (Serving: {WEBAPP_DIR})...")
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("", PORT), MiniAppHTTPRequestHandler) as httpd:
        logger.info(f"HTTP Server listening on http://0.0.0.0:{PORT}")
        httpd.serve_forever()


def keep_alive_worker():
    """Periodically pings the public URL to keep the Render free-tier container active."""
    base = (RENDER_EXTERNAL_URL or "https://firstcry-ttjq.onrender.com").rstrip("/")
    url = f"{base}/healthz"
    time.sleep(45)
    while True:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "RenderKeepAliveBot/1.0"})
            with urllib.request.urlopen(req, timeout=20) as resp:
                logger.info(f"Keep-alive self-ping sent to {url} (HTTP {resp.getcode()})")
        except Exception as e:
            logger.debug(f"Keep-alive self-ping notice: {e}")
        time.sleep(600)  # Ping every 10 minutes



def main():
    logger.info("=" * 60)
    logger.info("Initializing FirstCry Cloud Service for Render.com")
    logger.info("=" * 60)

    # 1. If RENDER_EXTERNAL_URL is available, sync Telegram WebApp button
    if RENDER_EXTERNAL_URL:
        logger.info(f"Detected Render External URL: {RENDER_EXTERNAL_URL}")
        sync_telegram_menu_button(RENDER_EXTERNAL_URL)

    # 2. Start HTTP server in a separate daemon thread
    http_thread = threading.Thread(target=run_http_server, daemon=True)
    http_thread.start()

    # 3. Start keep-alive worker in background
    ka_thread = threading.Thread(target=keep_alive_worker, daemon=True)
    ka_thread.start()

    # 4. Give HTTP server a moment to bind
    time.sleep(1)

    # 5. Start Telegram Bot polling in the main thread (keeps process alive 24/7)
    logger.info("Starting Telegram Bot Polling Runner...")
    telegram_bot.poll_updates()


if __name__ == "__main__":
    main()

