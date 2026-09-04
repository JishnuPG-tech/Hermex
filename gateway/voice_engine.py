import os
import io
import re
import asyncio
import logging
from typing import AsyncGenerator, List, Dict, Any, Optional

logger = logging.getLogger("hermes.voice_engine")

CURATED_VOICES = [
    {
        "id": "en-US-ChristopherNeural",
        "name": "Christopher (Jarvis / Deep Male)",
        "gender": "Male",
        "locale": "en-US",
        "recommended": True
    },
    {
        "id": "en-US-AriaNeural",
        "name": "Aria (Natural / Clear Female)",
        "gender": "Female",
        "locale": "en-US",
        "recommended": True
    },
    {
        "id": "en-GB-RyanNeural",
        "name": "Ryan (British Suave / Jarvis Style)",
        "gender": "Male",
        "locale": "en-GB",
        "recommended": False
    },
    {
        "id": "en-US-GuyNeural",
        "name": "Guy (Modern / Tech Male)",
        "gender": "Male",
        "locale": "en-US",
        "recommended": False
    },
    {
        "id": "en-US-JennyNeural",
        "name": "Jenny (Conversational Female)",
        "gender": "Female",
        "locale": "en-US",
        "recommended": False
    },
    {
        "id": "en-GB-SoniaNeural",
        "name": "Sonia (British Female)",
        "gender": "Female",
        "locale": "en-GB",
        "recommended": False
    }
]

async def synthesize_speech_stream(
    text: str,
    voice: str = "en-US-ChristopherNeural",
    rate: str = "+0%",
    pitch: str = "+0Hz"
) -> AsyncGenerator[bytes, None]:
    """Stream MP3 audio chunks using edge-tts (100% free neural synthesis)."""
    clean_text = text.strip()
    if not clean_text:
        return

    clean_text = re.sub(r'```[\s\S]*?```', ' (code omitted) ', clean_text)
    clean_text = re.sub(r'`([^`]+)`', r'\1', clean_text)
    clean_text = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', clean_text)
    clean_text = re.sub(r'[#*_~>]+', '', clean_text)
    clean_text = re.sub(r'<[^>]+>', '', clean_text).strip()

    if not clean_text:
        clean_text = "I've completed the operation."

    try:
        import edge_tts
        communicate = edge_tts.Communicate(clean_text, voice, rate=rate, pitch=pitch)
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                yield chunk["data"]
    except ImportError:
        logger.warning("edge-tts not installed, falling back to silent frame")
        yield b""
    except Exception as e:
        logger.error(f"Error during edge-tts streaming synthesis: {e}")
        yield b""

async def synthesize_speech_bytes(
    text: str,
    voice: str = "en-US-ChristopherNeural",
    rate: str = "+0%",
    pitch: str = "+0Hz"
) -> bytes:
    """Synthesize complete text into full MP3 audio bytes."""
    buf = io.BytesIO()
    async for chunk in synthesize_speech_stream(text, voice, rate, pitch):
        buf.write(chunk)
    return buf.getvalue()

def get_curated_voices() -> List[Dict[str, Any]]:
    """Return list of supported high-quality neural voices."""
    return CURATED_VOICES

async def synthesize_speech_pcm_stream(
    text: str,
    voice: str = "en-US-ChristopherNeural",
    rate: str = "+0%",
    pitch: str = "+0Hz"
) -> AsyncGenerator[bytes, None]:
    '''Synthesize speech and transcode MP3 stream to raw PCM 16000Hz 16-bit mono bytes for Android AudioTrack.'''
    clean_text = text.strip()
    if not clean_text:
        return

    clean_text = re.sub(r'```[\s\S]*?```', ' (code omitted) ', clean_text)
    clean_text = re.sub(r'`([^`]+)`', r'\1', clean_text)
    clean_text = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', clean_text)
    clean_text = re.sub(r'[#*_~>]+', '', clean_text)
    clean_text = re.sub(r'<[^>]+>', '', clean_text).strip()

    if not clean_text:
        clean_text = "I've completed the operation."

    try:
        import edge_tts
        mp3_bytes = io.BytesIO()
        communicate = edge_tts.Communicate(clean_text, voice, rate=rate, pitch=pitch)
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                mp3_bytes.write(chunk["data"])

        raw_mp3 = mp3_bytes.getvalue()
        if not raw_mp3:
            return

        # Convert MP3 to raw PCM 16kHz s16le mono using ffmpeg
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-hide_banner", "-loglevel", "error",
            "-i", "pipe:0",
            "-f", "s16le",
            "-acodec", "pcm_s16le",
            "-ar", "16000",
            "-ac", "1",
            "pipe:1",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout_data, stderr_data = await proc.communicate(input=raw_mp3)
        if stdout_data:
            chunk_size = 4096
            for i in range(0, len(stdout_data), chunk_size):
                yield stdout_data[i:i+chunk_size]
        else:
            # Fallback if ffmpeg missing
            yield raw_mp3
    except Exception as e:
        logger.error(f"PCM synthesis error: {e}")
