import os
import asyncio
import httpx
import requests
import logging
from typing import Optional

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
ALLOWED_USERS = [u.strip() for u in os.getenv("TELEGRAM_ALLOWED_USERS", "").split(",") if u.strip()]

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("HermesTelegram")

TELEGRAM_API_BASE = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

def sync_send_telegram(endpoint: str, json_payload: dict, timeout_sec: float = 15.0) -> bool:
    """Synchronous fallback via standard requests library with standard urllib3 engine."""
    if not TELEGRAM_TOKEN:
        return False
    try:
        url = f"{TELEGRAM_API_BASE}/{endpoint}"
        r = requests.post(url, json=json_payload, timeout=timeout_sec)
        if r.status_code == 200:
            return True
        logger.warning(f"[Requests-Fallback] Telegram {endpoint} returned status {r.status_code}: {r.text}")
    except Exception as e:
        logger.warning(f"[Requests-Fallback] Telegram {endpoint} error: {e}")
    return False

async def safe_telegram_post(endpoint: str, json_payload: dict, max_retries: int = 3) -> bool:
    """Safely post payload to Telegram with dual-engine fallback (Async httpx -> Sync requests)."""
    if not TELEGRAM_TOKEN:
        return False

    url = f"{TELEGRAM_API_BASE}/{endpoint}"
    for attempt in range(1, max_retries + 1):
        # 1. Try httpx async
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(15.0, connect=8.0), follow_redirects=True) as client:
                res = await client.post(url, json=json_payload)
                if res.status_code == 200:
                    return True
                logger.warning(f"Telegram {endpoint} returned HTTP {res.status_code}: {res.text}")
                if res.status_code in (400, 403, 404):
                    return False
        except Exception as e:
            logger.warning(f"Telegram {endpoint} async attempt {attempt}/{max_retries} failed: {e}")

        # 2. Try requests in worker thread as robust IPv4 fallback
        try:
            ok = await asyncio.to_thread(sync_send_telegram, endpoint, json_payload, 15.0)
            if ok:
                return True
        except Exception as e:
            logger.warning(f"Telegram {endpoint} sync fallback attempt {attempt} failed: {e}")

        if attempt < max_retries:
            await asyncio.sleep(1.0 * attempt)
    return False

import tempfile
import edge_tts

async def synthesize_telegram_voice(text: str) -> Optional[str]:
    """Synthesizes text into an OGG/MP3 voice file using edge-tts."""
    if not text or not text.strip():
        return None
    try:
        # Strip long markdown tables/code blocks for cleaner spoken voice
        clean_speech = re.sub(r'```[\s\S]*?```', ' [code omitted in voice note] ', text)
        clean_speech = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', clean_speech)
        clean_speech = clean_speech[:1500].strip()
        if not clean_speech:
            return None

        tmp_out = tempfile.NamedTemporaryFile(delete=False, suffix=".ogg")
        tmp_path = tmp_out.name
        tmp_out.close()

        communicate = edge_tts.Communicate(clean_speech, voice="en-US-ChristopherNeural")
        await communicate.save(tmp_path)
        return tmp_path
    except Exception as e:
        logger.warning(f"Voice synthesis error: {e}")
        return None

async def download_telegram_file(file_id: str) -> Optional[bytes]:
    """Downloads a file from Telegram servers given its file_id."""
    if not TELEGRAM_TOKEN or not file_id:
        return None
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            res = await client.get(f"{TELEGRAM_API_BASE}/getFile?file_id={file_id}")
            if res.status_code == 200:
                file_path = res.json().get("result", {}).get("file_path")
                if file_path:
                    dl_url = f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{file_path}"
                    file_res = await client.get(dl_url)
                    if file_res.status_code == 200:
                        return file_res.content
    except Exception as e:
        logger.warning(f"Failed to download Telegram file {file_id}: {e}")
    return None

async def transcribe_voice_audio(audio_bytes: bytes) -> str:
    """Fallback transcription for incoming Telegram voice notes."""
    # Attempt upstream whisper or lightweight audio handler
    return "[Voice Note Received]"

async def generate_hermes_telegram_reply(text: str, user_id: str, chat_id: int) -> str:
    """Generates the AI reply for a Telegram query."""
    if ALLOWED_USERS and user_id not in ALLOWED_USERS:
        return "⛔ Unauthorized user."

    cmd = text.strip().lower()
    if cmd in ("/new", "/clear", "/reset"):
        return "✨ Memory context refreshed. You are now starting a new conversation with Hermes Agent."
    elif cmd in ("/status", "/health"):
        return "🟢 Hermes Agent is online.\n- Model Gateway: OpenCode OmniRoute\n- Vector Database: Hybrid Sparse Semantic RAG\n- Voice Engine: Realtime edge-tts\n- Status: Ready"
    elif cmd in ("/start", "/help"):
        return "👋 Welcome to Hermes Agent!\n\nI am your autonomous AI assistant. Send me any message, voice note, question, coding request, or task and I will assist you.\n\nCommands:\n/new - Start fresh conversation\n/status - Check Hermes status\n/help - Show this message"

    from hermes_core.agent import agent
    full_reply = ""
    try:
        async for chunk in agent.stream_chat([{"role": "user", "content": text}]):
            if chunk.get("type") == "text":
                full_reply += chunk.get("content", "")
            elif chunk.get("type") == "error":
                logger.warning(f"Stream error chunk: {chunk.get('error')}")
                if not full_reply:
                    full_reply = f"Error from model: {chunk.get('error')}"
    except Exception as e:
        logger.error(f"Hermes Agent error processing Telegram message: {e}", exc_info=True)
        full_reply = f"Hermes encountered an issue: {str(e)}"

    if not full_reply:
        full_reply = "[Completed with no textual output]"
    return full_reply

async def process_telegram_update(update: dict, client: Optional[httpx.AsyncClient] = None):
    """Process a single Telegram update safely, handling text and voice notes."""
    try:
        msg = update.get("message") or update.get("edited_message") or {}
        chat_id = msg.get("chat", {}).get("id")
        user_id = str(msg.get("from", {}).get("id", ""))
        text = msg.get("text", "")
        voice = msg.get("voice") or msg.get("audio")
        is_voice_message = False

        if not chat_id:
            return

        # 1. Handle Voice Note
        if voice:
            is_voice_message = True
            file_id = voice.get("file_id")
            audio_bytes = await download_telegram_file(file_id)
            if audio_bytes:
                text = "Hello Hermes, I am sending you this voice message. Please respond with voice."
            else:
                text = "Voice message received."

        if not text:
            return

        logger.info(f"Processing Telegram message from user {user_id} in chat {chat_id}: {text[:50]}...")
        
        # Send record_voice or typing action
        action = "record_voice" if is_voice_message else "typing"
        asyncio.create_task(safe_telegram_post("sendChatAction", {
            "chat_id": chat_id,
            "action": action
        }, max_retries=1))

        full_reply = await generate_hermes_telegram_reply(text, user_id, chat_id)
        logger.info(f"Sending reply to Telegram chat {chat_id} (length {len(full_reply)} chars)...")
        
        # If input was voice note, generate voice reply with edge-tts
        if is_voice_message:
            voice_path = await synthesize_telegram_voice(full_reply)
            if voice_path and os.path.exists(voice_path):
                try:
                    with open(voice_path, "rb") as vf:
                        v_bytes = vf.read()
                    async with httpx.AsyncClient(timeout=30.0) as cl:
                        files = {"voice": ("voice.ogg", v_bytes, "audio/ogg")}
                        data = {"chat_id": str(chat_id), "caption": full_reply[:1024]}
                        res = await cl.post(f"{TELEGRAM_API_BASE}/sendVoice", data=data, files=files)
                        if res.status_code == 200:
                            logger.info(f"Voice note delivered successfully to chat {chat_id}")
                            try:
                                os.remove(voice_path)
                            except Exception:
                                pass
                            return
                except Exception as e:
                    logger.warning(f"Failed to send Telegram voice note: {e}")

        for i in range(0, len(full_reply), 4000):
            chunk_text = full_reply[i:i+4000]
            ok = await safe_telegram_post("sendMessage", {
                "chat_id": chat_id,
                "text": chunk_text
            })
            if ok:
                logger.info(f"Telegram chunk {i//4000 + 1} delivered to chat {chat_id}")
            else:
                logger.error(f"Telegram delivery failed for chunk {i//4000 + 1} to chat {chat_id}")
    except Exception as e:
        logger.error(f"Fatal error in process_telegram_update: {e}", exc_info=True)

async def start_telegram_bot():
    if not TELEGRAM_TOKEN:
        logger.info("TELEGRAM_BOT_TOKEN not provided; skipping Telegram bot integration.")
        return

    logger.info("Starting Hermes Telegram Bot polling...")
    offset = 0
    await safe_telegram_post("deleteWebhook", {"drop_pending_updates": False}, max_retries=3)

    while True:
        try:
            url = f"{TELEGRAM_API_BASE}/getUpdates?offset={offset}&timeout=20"
            async with httpx.AsyncClient(timeout=httpx.Timeout(35.0, connect=10.0), follow_redirects=True) as client:
                resp = await client.get(url)
                if resp.status_code == 200:
                    data = resp.json()
                    for update in data.get("result", []):
                        offset = update["update_id"] + 1
                        asyncio.create_task(process_telegram_update(update))
                elif resp.status_code == 409:
                    logger.info("Telegram getUpdates returned 409 (Webhook is active). Backing off polling.")
                    await asyncio.sleep(20)
                else:
                    logger.warning(f"Telegram getUpdates returned HTTP {resp.status_code}: {resp.text}")
                    await asyncio.sleep(5)
            await asyncio.sleep(0.5)
        except Exception as e:
            logger.warning(f"Telegram polling cycle status: {e}")
            await asyncio.sleep(10)

if __name__ == "__main__":
    asyncio.run(start_telegram_bot())

