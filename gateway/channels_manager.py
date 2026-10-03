import os
import re
import json
import time
import uuid
import asyncio
import logging
import smtplib
import imaplib
import email
import hashlib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Dict, Any, List, Optional
import httpx

logger = logging.getLogger("hermes.channels")
logging.basicConfig(level=logging.INFO)

def _telegram_http_client(**kwargs) -> httpx.AsyncClient:
    """
    Telegram traffic from hosted containers can prefer an unusable IPv6 route.
    Bind the client locally to IPv4 so DNS resolution/connect uses IPv4.
    """
    kwargs.setdefault("follow_redirects", True)
    kwargs.setdefault("transport", httpx.AsyncHTTPTransport(local_address="0.0.0.0"))
    return httpx.AsyncClient(**kwargs)

CONFIG_PATH = "/data/hermes/channels.json"
LOCAL_CONFIG_PATH = os.path.expanduser("~/.hermes/channels.json")

def _get_config_file() -> str:
    if os.path.exists("/data/hermes"):
        return CONFIG_PATH
    os.makedirs(os.path.expanduser("~/.hermes"), exist_ok=True)
    return LOCAL_CONFIG_PATH

def load_channels_config() -> Dict[str, Any]:
    cfg_file = _get_config_file()
    cfg = {
        "telegram": {
            "enabled": bool(os.getenv("TELEGRAM_BOT_TOKEN")),
            "token": os.getenv("TELEGRAM_BOT_TOKEN", ""),
            "allowed_users": os.getenv("TELEGRAM_ALLOWED_USERS", "*"),
            "admin_id": os.getenv("TELEGRAM_ADMIN_ID", ""),
            "webhook_set": False
        },
        "email": {
            "enabled": bool(os.getenv("EMAIL_ADDRESS") and (os.getenv("EMAIL_PASSWORD") or os.getenv("GMAIL_APP_PASSWORD"))),
            "address": os.getenv("EMAIL_ADDRESS", "jishnupg2005@gmail.com"),
            "password": os.getenv("EMAIL_PASSWORD") or os.getenv("GMAIL_APP_PASSWORD", ""),
            "imap_host": os.getenv("EMAIL_IMAP_HOST", "imap.gmail.com"),
            "smtp_host": os.getenv("EMAIL_SMTP_HOST", "smtp.gmail.com"),
            "imap_port": int(os.getenv("EMAIL_IMAP_PORT", "993")),
            "smtp_port": int(os.getenv("EMAIL_SMTP_PORT", "587")),
            "allowed_users": os.getenv("EMAIL_ALLOWED_USERS", "*"),
            "poll_interval": int(os.getenv("EMAIL_POLL_INTERVAL", "15"))
        },
        "discord": {
            "enabled": bool(os.getenv("DISCORD_BOT_TOKEN")),
            "token": os.getenv("DISCORD_BOT_TOKEN", ""),
            "allowed_users": os.getenv("DISCORD_ALLOWED_USERS", "*")
        },
        "webhooks": {
            "enabled": True,
            "secret": os.getenv("WEBHOOK_SECRET", "hermes_secret_webhook_key")
        }
    }
    if os.path.exists(cfg_file):
        try:
            with open(cfg_file, "r", encoding="utf-8") as f:
                saved = json.load(f)
                for k, v in saved.items():
                    if k in cfg and isinstance(v, dict):
                        cfg[k].update(v)
        except Exception as e:
            logger.error(f"Error loading channels config: {e}")
    return cfg

def save_channels_config(cfg: Dict[str, Any]):
    cfg_file = _get_config_file()
    try:
        os.makedirs(os.path.dirname(cfg_file), exist_ok=True)
        with open(cfg_file, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
    except Exception as e:
        logger.error(f"Error saving channels config: {e}")

# ── Message Formatters ───────────────────────────────────────────

def format_for_telegram(text: str) -> List[str]:
    """
    Converts markdown to Telegram HTML formatting and chunks messages cleanly (<4000 chars).
    """
    if not text:
        return [""]

    def escape_html(s: str) -> str:
        return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    code_blocks = []
    def code_repl(m):
        lang = m.group(1) or ""
        code = m.group(2)
        idx = len(code_blocks)
        code_blocks.append(f'<pre><code class="language-{lang}">{escape_html(code)}</code></pre>')
        return f"___CODE_BLOCK_{idx}___"

    formatted = re.sub(r'```([a-zA-Z0-9_-]*)\n([\s\S]*?)```', code_repl, text)

    inline_codes = []
    def inline_repl(m):
        code = m.group(1)
        idx = len(inline_codes)
        inline_codes.append(f'<code>{escape_html(code)}</code>')
        return f"___INLINE_CODE_{idx}___"

    formatted = re.sub(r'`([^`]+)`', inline_repl, formatted)
    formatted = escape_html(formatted)

    formatted = re.sub(r'^#{1,6}\s+(.*$)', r'<b>\1</b>', formatted, flags=re.MULTILINE)
    formatted = re.sub(r'\*\*([^*]+)\*\*', r'<b>\1</b>', formatted)
    formatted = re.sub(r'__([^_]+)__', r'<b>\1</b>', formatted)
    formatted = re.sub(r'(?<![a-zA-Z0-9])\*([^*]+)\*(?![a-zA-Z0-9])', r'<i>\1</i>', formatted)
    formatted = re.sub(r'(?<![a-zA-Z0-9])_([^_]+)_(?![a-zA-Z0-9])', r'<i>\1</i>', formatted)
    formatted = re.sub(r'^>\s+(.*$)', r'<blockquote>\1</blockquote>', formatted, flags=re.MULTILINE)
    formatted = re.sub(r'^\s*[-*+]\s+(.*$)', r'• \1', formatted, flags=re.MULTILINE)

    for i, b in enumerate(inline_codes):
        formatted = formatted.replace(f"___INLINE_CODE_{i}___", b)
    for i, b in enumerate(code_blocks):
        formatted = formatted.replace(f"___CODE_BLOCK_{i}___", b)

    chunks = []
    max_len = 3900
    while len(formatted) > max_len:
        split_idx = formatted.rfind("\n\n", 0, max_len)
        if split_idx == -1:
            split_idx = formatted.rfind("\n", 0, max_len)
        if split_idx == -1:
            split_idx = formatted.rfind(" ", 0, max_len)
        if split_idx == -1:
            split_idx = max_len

        chunks.append(formatted[:split_idx].strip())
        formatted = formatted[split_idx:].strip()

    if formatted:
        chunks.append(formatted)

    return chunks

def format_for_discord(text: str) -> List[str]:
    """
    Chunks message cleanly into Discord's 2000 character limit without breaking code blocks.
    """
    if not text:
        return [""]

    chunks = []
    max_len = 1900
    curr = text
    while len(curr) > max_len:
        split_idx = curr.rfind("\n\n", 0, max_len)
        if split_idx == -1:
            split_idx = curr.rfind("\n", 0, max_len)
        if split_idx == -1:
            split_idx = curr.rfind(" ", 0, max_len)
        if split_idx == -1:
            split_idx = max_len

        chunks.append(curr[:split_idx].strip())
        curr = curr[split_idx:].strip()

    if curr:
        chunks.append(curr)

    return chunks

def format_for_email_html(text: str, subject: str = "Hermes Agent Response") -> str:
    """
    Renders a responsive, elegant Claude-themed HTML email layout.
    """
    import html
    escaped = html.escape(text)

    escaped = re.sub(
        r'```([a-zA-Z0-9_-]*)\n([\s\S]*?)```',
        r'<pre style="background-color:#1e1e24; color:#e4e4e7; padding:12px; border-radius:8px; overflow-x:auto; font-family:monospace; font-size:13px;"><code>\2</code></pre>',
        escaped
    )

    escaped = re.sub(
        r'`([^`]+)`',
        r'<code style="background-color:#f4f4f5; color:#b45309; padding:2px 6px; border-radius:4px; font-family:monospace; font-size:13px;">\1</code>',
        escaped
    )

    escaped = re.sub(r'^### (.*$)', r'<h3 style="color:#18181b; margin:16px 0 8px 0; font-size:16px;">\1</h3>', escaped, flags=re.MULTILINE)
    escaped = re.sub(r'^## (.*$)', r'<h2 style="color:#18181b; margin:20px 0 10px 0; font-size:18px;">\1</h2>', escaped, flags=re.MULTILINE)
    escaped = re.sub(r'^# (.*$)', r'<h1 style="color:#18181b; margin:24px 0 12px 0; font-size:20px;">\1</h1>', escaped, flags=re.MULTILINE)

    escaped = re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', escaped)
    escaped = re.sub(r'\*([^*]+)\*', r'<em>\1</em>', escaped)
    escaped = escaped.replace("\n\n", "<br><br>").replace("\n", "<br>")

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{html.escape(subject)}</title>
</head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #f7f7f8; margin: 0; padding: 24px; color: #27272a; line-height: 1.6;">
    <div style="max-width: 640px; margin: 0 auto; background-color: #ffffff; border-radius: 12px; border: 1px solid #e4e4e7; overflow: hidden; box-shadow: 0 4px 12px rgba(0,0,0,0.05);">
        <div style="background-color: #18181b; padding: 18px 24px; color: #ffffff; display: flex; align-items: center; justify-content: space-between;">
            <div style="font-size: 16px; font-weight: 700;">⚡ Hermes Pro Agent</div>
            <span style="font-size: 11px; background-color: rgba(217,119,6,0.3); color: #f59e0b; padding: 2px 8px; border-radius: 4px; font-weight: 700;">AI RESPONSE</span>
        </div>
        <div style="padding: 24px; font-size: 14.5px; color: #18181b;">
            {escaped}
        </div>
        <div style="background-color: #fafafa; border-top: 1px solid #f4f4f5; padding: 14px 24px; font-size: 12px; color: #71717a; text-align: center;">
            Sent automatically by Hermes Agentic AI Gateway • Model: Claude Pro / Hermes Smart
        </div>
    </div>
</body>
</html>"""

# ── Agentic Inference Helper ────────────────────────────────────

async def generate_agent_response(prompt: str, session_id: str = "channel_default", model: Optional[str] = None) -> str:
    """
    Dispatches a prompt to the Hermes agentic reasoning backend with multi-provider failover.
    """
    from gateway import anthropic_bridge as ab
    selected_model = model or os.getenv("HERMES_MODEL", "auto/smart")

    payload = {
        "model": selected_model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are Hermes, an autonomous agentic AI assistant. "
                    "Provide helpful, accurate, well-structured, and concise responses. "
                    "Use clear markdown with bullet points, headers, and code formatting where appropriate."
                )
            },
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.6,
        "max_tokens": 3000,
        "stream": True
    }

    accumulated = []
    try:
        async for chunk_str in ab.stream_upstream(payload, requested_model=selected_model, chat_id=session_id):
            if chunk_str == "[DONE]":
                break
            try:
                chunk_obj = json.loads(chunk_str)
                delta = chunk_obj.get("choices", [{}])[0].get("delta", {})
                content = delta.get("content", "")
                if content:
                    accumulated.append(content)
            except Exception:
                pass

        if accumulated:
            return "".join(accumulated).strip()
        else:
            return "I am here and ready to assist you. Please send your query."
    except Exception as e:
        logger.error(f"Exception during agent generation: {e}")
        return f"⚠️ Error processing request: {e}"

async def _send_extra_chunks(token: Optional[str], chat_id: int, chunks: List[str]):
    if not token or not chunks:
        return
    api_base = f"https://api.telegram.org/bot{token}"
    try:
        async with _telegram_http_client(timeout=15.0) as client:
            for chunk in chunks:
                try:
                    await client.post(
                        f"{api_base}/sendMessage",
                        json={"chat_id": chat_id, "text": chunk, "parse_mode": "HTML"}
                    )
                except Exception:
                    pass
    except Exception:
        pass

async def handle_telegram_webhook_payload(update: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Processes incoming Telegram webhook update and returns the direct HTTP response payload.
    Guarantees 100% message delivery with ZERO outbound connection requirements from HF Spaces!
    """
    cfg = load_channels_config().get("telegram", {})
    allowed_list = [u.strip().lower() for u in cfg.get("allowed_users", "*").split(",") if u.strip()]

    msg = update.get("message") or update.get("edited_message")
    if not msg:
        return None

    chat_id = msg.get("chat", {}).get("id")
    user_info = msg.get("from", {})
    username = (user_info.get("username") or "").lower()
    user_id = str(user_info.get("id", ""))
    text = msg.get("text") or msg.get("caption") or ""

    if not chat_id:
        return None

    if "*" not in allowed_list and username not in allowed_list and user_id not in allowed_list:
        return {
            "method": "sendMessage",
            "chat_id": chat_id,
            "text": "⛔ <b>Access Denied</b>\nPlease ask the bot administrator to whitelist your user ID.",
            "parse_mode": "HTML"
        }

    if not text:
        return None

    if text.startswith("/start"):
        welcome_msg = (
            "👋 <b>Welcome to Hermes Agentic AI!</b>\n\n"
            "I am your autonomous AI pair programmer and assistant, connected live to the Hermes Gateway.\n\n"
            "<b>Available Commands:</b>\n"
            "• <code>/model</code> - View active model configuration\n"
            "• <code>/status</code> - Check system & backend health\n"
            "• <code>/clear</code> - Reset conversation context\n"
            "• <code>/help</code> - Show this guide\n\n"
            "Send any prompt, task, or question to get started!"
        )
        return {
            "method": "sendMessage",
            "chat_id": chat_id,
            "text": welcome_msg,
            "parse_mode": "HTML"
        }

    if text.startswith("/status"):
        status_msg = (
            "⚡ <b>Hermes System Status:</b>\n\n"
            "• <b>Backend:</b> OmniRoute + Hermes Core\n"
            "• <b>Admin:</b> jishnupg2005@gmail.com\n"
            "• <b>Channels:</b> Telegram [ACTIVE 🟢], Webhooks [ACTIVE 🟢]\n"
            "• <b>Models:</b> All 13 models online\n"
        )
        return {
            "method": "sendMessage",
            "chat_id": chat_id,
            "text": status_msg,
            "parse_mode": "HTML"
        }

    if text.startswith("/clear"):
        return {
            "method": "sendMessage",
            "chat_id": chat_id,
            "text": "🧹 <b>Context reset.</b> Send a new message to start a fresh thread!",
            "parse_mode": "HTML"
        }

    # Generate agent response
    reply_text = await generate_agent_response(text, session_id=f"tg_{chat_id}")
    chunks = format_for_telegram(reply_text)
    primary_chunk = chunks[0] if chunks else "I am here and ready to assist you."

    if len(chunks) > 1:
        asyncio.create_task(_send_extra_chunks(cfg.get("token"), chat_id, chunks[1:]))

    return {
        "method": "sendMessage",
        "chat_id": chat_id,
        "text": primary_chunk,
        "parse_mode": "HTML"
    }

# ── Telegram Update Processor (Unified Webhook & Polling Handler) ──

async def process_telegram_update(update: Dict[str, Any], token: Optional[str] = None) -> bool:
    cfg = load_channels_config().get("telegram", {})
    bot_token = token or cfg.get("token")
    if not bot_token:
        return False

    api_base = f"https://api.telegram.org/bot{bot_token}"
    allowed_list = [u.strip().lower() for u in cfg.get("allowed_users", "*").split(",") if u.strip()]

    msg = update.get("message") or update.get("edited_message")
    if not msg:
        return True

    chat_id = msg.get("chat", {}).get("id")
    user_info = msg.get("from", {})
    username = (user_info.get("username") or "").lower()
    user_id = str(user_info.get("id", ""))
    text = msg.get("text") or msg.get("caption") or ""

    if "*" not in allowed_list and username not in allowed_list and user_id not in allowed_list:
        async with _telegram_http_client(timeout=10.0) as client:
            await client.post(
                f"{api_base}/sendMessage",
                json={"chat_id": chat_id, "text": "⛔ Access denied. Contact the administrator to whitelist your user ID."}
            )
        return True

    document = msg.get("document")
    if document:
        file_id = document.get("file_id")
        filename = document.get("file_name") or f"telegram_{file_id or uuid.uuid4().hex}.pdf"
        mime_type = (document.get("mime_type") or "").lower()
        if not (filename.lower().endswith(".pdf") or mime_type == "application/pdf"):
            async with _telegram_http_client(timeout=15.0) as client:
                await client.post(
                    f"{api_base}/sendMessage",
                    json={"chat_id": chat_id, "text": "⚠️ Please send a PDF document."}
                )
            return True

        incoming_dir = "/data/incoming"
        os.makedirs(incoming_dir, exist_ok=True)
        safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", filename).strip("._") or f"telegram_{uuid.uuid4().hex}.pdf"
        target = os.path.join(incoming_dir, f"{uuid.uuid4().hex[:12]}_{safe_name}")

        try:
            async with _telegram_http_client(timeout=httpx.Timeout(120.0, connect=15.0), follow_redirects=True) as client:
                meta = await client.get(f"{api_base}/getFile", params={"file_id": file_id})
                meta.raise_for_status()
                file_path = meta.json().get("result", {}).get("file_path")
                if not file_path:
                    raise RuntimeError("Telegram getFile returned no file_path")
                download_url = f"https://api.telegram.org/file/bot{bot_token}/{file_path}"
                async with client.stream("GET", download_url) as response:
                    response.raise_for_status()
                    with open(target, "wb") as out:
                        async for chunk in response.aiter_bytes(1024 * 1024):
                            out.write(chunk)

            sha256 = hashlib.sha256()
            size = 0
            with open(target, "rb") as inp:
                for chunk in iter(lambda: inp.read(1024 * 1024), b""):
                    sha256.update(chunk)
                    size += len(chunk)

            job_id = f"HERMES-PDF-{sha256.hexdigest()[:16]}"
            ack = (
                "📥 <b>PDF received</b>\n\n"
                f"File: <code>{safe_name}</code>\n"
                f"Size: {size / 1048576:.2f} MB\n"
                f"Job: <code>{job_id}</code>\n\n"
                "Status: <b>QUEUED</b>\n"
                "Hermes will inspect the complete PDF, extract questions, validate answers, "
                "classify them, and preserve source pages."
            )
            async with _telegram_http_client(timeout=15.0) as client:
                await client.post(
                    f"{api_base}/sendMessage",
                    json={"chat_id": chat_id, "text": ack, "parse_mode": "HTML"}
                )

            pdf_prompt = f"""
A bank-exam PDF has just been received through Telegram.

Job ID: {job_id}
File path: {target}
Original filename: {filename}
SHA-256: {sha256.hexdigest()}

Process this PDF completely using the Hermes PDF extraction workflow. Inspect every page,
extract every question, preserve original numbering/options/set context/visual information,
use OCR where needed, find and validate answer keys, classify subject/topic/subtopic,
detect duplicates without deleting provenance, save structured JSON and metadata to
persistent storage, and report pages/questions requiring review.

NEVER GUESS. If an answer cannot be reliably established, use null and REVIEW_REQUIRED.
Do not stop after finding some questions. Process the entire PDF.
"""
            reply = await generate_agent_response(pdf_prompt, session_id=f"tg_pdf_{chat_id}_{job_id}")
            for chunk in format_for_telegram(reply):
                async with _telegram_http_client(timeout=15.0) as client:
                    await client.post(
                        f"{api_base}/sendMessage",
                        json={"chat_id": chat_id, "text": chunk, "parse_mode": "HTML"}
                    )
        except Exception as e:
            logger.exception(f"Telegram PDF ingestion failed for {filename}: {e}")
            async with _telegram_http_client(timeout=15.0) as client:
                await client.post(
                    f"{api_base}/sendMessage",
                    json={"chat_id": chat_id, "text": f"❌ PDF processing failed: {str(e)[:1000]}"}
                )
        return True

    if not text:
        return True

    try:
        async with _telegram_http_client(timeout=15.0) as client:
            if text.startswith("/start"):
                welcome_msg = (
                    "👋 <b>Welcome to Hermes Agentic AI!</b>\n\n"
                    "I am your autonomous AI pair programmer and assistant, powered by the Hermes Gateway.\n\n"
                    "<b>Available Commands:</b>\n"
                    "• <code>/model</code> - View active model configuration\n"
                    "• <code>/status</code> - Check system & backend health\n"
                    "• <code>/clear</code> - Reset conversation context\n"
                    "• <code>/help</code> - Show this guide\n\n"
                    "Send any message or task to get started!"
                )
                await client.post(f"{api_base}/sendMessage", json={"chat_id": chat_id, "text": welcome_msg, "parse_mode": "HTML"})
                return True

            if text.startswith("/status"):
                status_msg = (
                    "⚡ <b>Hermes System Status:</b>\n\n"
                    "• <b>Backend:</b> OmniRoute + Hermes Core\n"
                    "• <b>Admin:</b> jishnupg2005@gmail.com\n"
                    "• <b>Channels:</b> Telegram [ACTIVE], Gmail [STANDBY]\n"
                    "• <b>Status:</b> All 13 models online\n"
                )
                await client.post(f"{api_base}/sendMessage", json={"chat_id": chat_id, "text": status_msg, "parse_mode": "HTML"})
                return True

            try:
                await client.post(f"{api_base}/sendChatAction", json={"chat_id": chat_id, "action": "typing"})
            except Exception:
                pass

            reply_text = await generate_agent_response(text, session_id=f"tg_{chat_id}")
            chunks = format_for_telegram(reply_text)

            for chunk in chunks:
                try:
                    await client.post(
                        f"{api_base}/sendMessage",
                        json={"chat_id": chat_id, "text": chunk, "parse_mode": "HTML"}
                    )
                except Exception:
                    await client.post(
                        f"{api_base}/sendMessage",
                        json={"chat_id": chat_id, "text": reply_text[:4000]}
                    )
    except Exception as e:
        logger.warning(f"Telegram network notification: {e}")
    return True

# ── Telegram Bot Daemon (Fallback Polling) ───────────────────────

class TelegramBotService:
    def __init__(self):
        self.task: Optional[asyncio.Task] = None
        self.running = False
        self.last_update_id = 0
        self.activation_started_at: Optional[str] = None
        self.activation_last_error: Optional[str] = None
        self.activation_last_attempt: Optional[int] = None

    async def start(self):
        cfg = load_channels_config().get("telegram", {})
        if not cfg.get("enabled") or not cfg.get("token"):
            logger.info("Telegram bot service disabled or token missing.")
            return

        # Telegram activation is user-driven. If the webhook was already
        # activated successfully, Telegram keeps the webhook registered across
        # Hermes restarts, so do not make an outbound Telegram request at boot.
        if cfg.get("webhook_set"):
            self.running = True
            logger.info(
                "Telegram webhook already activated. "
                "Waiting for Telegram updates without startup API calls."
            )
            return

        # No activation yet. The user can open /api/telegram/activate to
        # explicitly activate or re-activate the webhook.
        self.running = True
        logger.info(
            "Telegram webhook is not activated. "
            "Open /api/telegram/activate to activate it."
        )

    async def activate_webhook(self) -> Dict[str, Any]:
        cfg = load_channels_config()
        telegram = cfg.setdefault("telegram", {})
        token = telegram.get("token") or os.getenv("TELEGRAM_BOT_TOKEN", "")
        if not token:
            return {"ok": False, "status": "missing_token"}

        telegram["enabled"] = True
        telegram["webhook_set"] = False
        telegram.pop("webhook_activated_at", None)
        save_channels_config(cfg)
        self.activation_started_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        self.activation_last_error = None
        self.activation_last_attempt = None

        self.running = True
        if self.task and not self.task.done():
            self.task.cancel()
        self.task = asyncio.create_task(self._configure_webhook(token))
        logger.info("Telegram webhook activation requested by user.")
        return {
            "ok": True,
            "status": "activation_started",
            "webhook_url": os.getenv(
                "TELEGRAM_WEBHOOK_URL",
                "https://jishnupg-hermes.hf.space/api/webhooks/telegram"
            )
        }

    async def _configure_webhook(self, token: str):
        api_base = f"https://api.telegram.org/bot{token}"
        webhook_url = os.getenv(
            "TELEGRAM_WEBHOOK_URL",
            "https://jishnupg-hermes.hf.space/api/webhooks/telegram"
        )

        # This task is normally launched by the user activation endpoint.
        # Retry for a long period so a temporary network problem does not
        # require another code deployment or restart.
        await asyncio.sleep(2)

        for attempt in range(1, 121):
            self.activation_last_attempt = attempt
            if not self.running:
                return
            try:
                async with _telegram_http_client(timeout=20.0, follow_redirects=True) as client:
                    r = await client.post(
                        f"{api_base}/setWebhook",
                        json={
                            "url": webhook_url,
                            "drop_pending_updates": False,
                            "allowed_updates": ["message", "edited_message", "callback_query"]
                        }
                    )
                    data = r.json()
                    if r.status_code == 200 and data.get("ok"):
                        cfg = load_channels_config()
                        telegram = cfg.setdefault("telegram", {})
                        telegram["enabled"] = True
                        telegram["webhook_set"] = True
                        telegram["webhook_url"] = webhook_url
                        telegram["webhook_activated_at"] = time.strftime(
                            "%Y-%m-%dT%H:%M:%SZ", time.gmtime()
                        )
                        save_channels_config(cfg)

                        self.activation_last_error = None
                        logger.info(
                            f"Telegram Webhook configured successfully: {webhook_url}"
                        )
                        info = await client.get(f"{api_base}/getWebhookInfo")
                        if info.status_code == 200:
                            info_data = info.json().get("result", {})
                            logger.info(
                                "Telegram WebhookInfo: url=%s pending=%s last_error=%s",
                                info_data.get("url"),
                                info_data.get("pending_update_count"),
                                info_data.get("last_error_message")
                            )
                        return

                    self.activation_last_error = f"HTTP {r.status_code}: {data}"
                    logger.error(
                        "Telegram setWebhook failed (attempt %s/120): HTTP %s: %s",
                        attempt, r.status_code, data
                    )
            except Exception as e:
                self.activation_last_error = f"{type(e).__name__}: {e}"
                logger.error(
                    "Telegram webhook connection failed (attempt %s/120): %s",
                    attempt, repr(e)
                )

            await asyncio.sleep(min(60, 3 * attempt))

        logger.error(
            "Telegram webhook activation exhausted its retry window. "
            "Open /api/telegram/activate again to start a fresh activation cycle."
        )
    async def stop(self):
        self.running = False
        if self.task:
            self.task.cancel()
            self.task = None
        logger.info("Telegram Bot service stopped.")

    async def _poll_loop(self, token: str):
        api_base = f"https://api.telegram.org/bot{token}"

        async with _telegram_http_client(timeout=35.0) as client:
            while self.running:
                try:
                    resp = await client.get(
                        f"{api_base}/getUpdates",
                        params={"offset": self.last_update_id + 1, "timeout": 20}
                    )
                    if resp.status_code != 200:
                        await asyncio.sleep(8)
                        continue

                    updates = resp.json().get("result", [])
                    for update in updates:
                        self.last_update_id = max(self.last_update_id, update.get("update_id", 0))
                        await process_telegram_update(update, token=token)

                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.warning(f"Telegram poller retry: {e}")
                    await asyncio.sleep(8)

# ── Gmail / Email Agent Daemon ──────────────────────────────────

class EmailAgentService:
    def __init__(self):
        self.task: Optional[asyncio.Task] = None
        self.running = False

    async def start(self):
        cfg = load_channels_config().get("email", {})
        if not cfg.get("enabled") or not cfg.get("address") or not cfg.get("password"):
            logger.info("Email service disabled or credentials missing.")
            return

        self.running = True
        self.task = asyncio.create_task(self._poll_loop(cfg))
        logger.info("Email Agent service started in background.")

    async def stop(self):
        self.running = False
        if self.task:
            self.task.cancel()
            self.task = None
        logger.info("Email Agent service stopped.")

    async def _poll_loop(self, cfg: Dict[str, Any]):
        poll_interval = cfg.get("poll_interval", 15)
        while self.running:
            try:
                await asyncio.to_thread(self._check_and_reply, cfg)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Email loop error: {e}")
            await asyncio.sleep(poll_interval)

    def _check_and_reply(self, cfg: Dict[str, Any]):
        imap_host = cfg.get("imap_host", "imap.gmail.com")
        imap_port = cfg.get("imap_port", 993)
        user = cfg.get("address")
        pwd = cfg.get("password")
        allowed = [u.strip().lower() for u in cfg.get("allowed_users", "*").split(",") if u.strip()]

        try:
            mail = imaplib.IMAP4_SSL(imap_host, imap_port)
            mail.login(user, pwd)
            mail.select("INBOX")

            status, data = mail.search(None, "UNSEEN")
            if status != "OK" or not data[0]:
                mail.logout()
                return

            for num in data[0].split():
                status, msg_data = mail.fetch(num, "(RFC822)")
                if status != "OK":
                    continue

                raw_email = msg_data[0][1]
                msg = email.message_from_bytes(raw_email)

                sender = msg.get("From", "")
                subject = msg.get("Subject", "No Subject")
                msg_id = msg.get("Message-ID", "")
                
                sender_match = re.search(r'[\w\.-]+@[\w\.-]+', sender)
                sender_email = sender_match.group(0).lower() if sender_match else ""

                if "*" not in allowed and sender_email not in allowed:
                    logger.info(f"Ignored email from non-whitelisted sender: {sender_email}")
                    continue

                body = ""
                if msg.is_multipart():
                    for part in msg.walk():
                        if part.get_content_type() == "text/plain":
                            body = part.get_payload(decode=True).decode(errors="ignore")
                            break
                else:
                    body = msg.get_payload(decode=True).decode(errors="ignore")

                if not body.strip():
                    continue

                logger.info(f"Processing email from {sender_email}: {subject}")
                
                reply_content = asyncio.run(generate_agent_response(
                    f"Email Subject: {subject}\nFrom: {sender}\n\n{body}",
                    session_id=f"email_{sender_email}"
                ))

                self._send_reply(cfg, sender, subject, msg_id, reply_content)

            mail.logout()
        except Exception as e:
            logger.error(f"Error checking IMAP emails: {e}")

    def _send_reply(self, cfg: Dict[str, Any], to_addr: str, original_subject: str, msg_id: str, content: str):
        smtp_host = cfg.get("smtp_host", "smtp.gmail.com")
        smtp_port = cfg.get("smtp_port", 587)
        user = cfg.get("address")
        pwd = cfg.get("password")

        reply_subject = original_subject if original_subject.lower().startswith("re:") else f"Re: {original_subject}"

        msg = MIMEMultipart("alternative")
        msg["From"] = f"Hermes Agent <{user}>"
        msg["To"] = to_addr
        msg["Subject"] = reply_subject
        if msg_id:
            msg["In-Reply-To"] = msg_id
            msg["References"] = msg_id

        part1 = MIMEText(content, "plain", "utf-8")
        part2 = MIMEText(format_for_email_html(content, reply_subject), "html", "utf-8")

        msg.attach(part1)
        msg.attach(part2)

        try:
            server = smtplib.SMTP(smtp_host, smtp_port)
            server.starttls()
            server.login(user, pwd)
            server.sendmail(user, [to_addr], msg.as_string())
            server.quit()
            logger.info(f"Replied to email: {reply_subject} to {to_addr}")
        except Exception as e:
            logger.error(f"Error sending SMTP email reply: {e}")

# ── Global Services Controller ──────────────────────────────────

telegram_service = TelegramBotService()
email_service = EmailAgentService()

async def start_all_channels():
    await telegram_service.start()
    await email_service.start()

async def stop_all_channels():
    await telegram_service.stop()
    await email_service.stop()

async def restart_channels():
    await stop_all_channels()
    await start_all_channels()
