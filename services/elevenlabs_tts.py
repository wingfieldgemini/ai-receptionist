"""ElevenLabs text-to-speech — streaming with native ulaw_8000 output for Twilio."""

from __future__ import annotations
import base64
import re
import logging
from typing import AsyncGenerator

import httpx

from config import ELEVENLABS_API_KEY, ELEVENLABS_VOICE_ID, ELEVENLABS_MODEL

logger = logging.getLogger(__name__)

ELEVENLABS_URL = f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVENLABS_VOICE_ID}"
ELEVENLABS_STREAM_URL = f"{ELEVENLABS_URL}/stream"

# Reusable HTTP client with connection pooling
_http_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(
            timeout=30.0,
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
            headers={
                "xi-api-key": ELEVENLABS_API_KEY,
                "Content-Type": "application/json",
            },
        )
    return _http_client


def _make_payload(text: str) -> dict:
    return {
        "text": text,
        "model_id": ELEVENLABS_MODEL,
        "voice_settings": {
            "stability": 0.5,
            "similarity_boost": 0.75,
            "style": 0.0,
            "use_speaker_boost": True,
        },
    }


def _split_sentences(text: str) -> list[str]:
    sentences = re.split(r'(?<=[.!?])\s+', text)
    return [s.strip() for s in sentences if s.strip()]


async def synthesize_stream(text: str) -> AsyncGenerator[bytes, None]:
    """Stream raw ulaw_8000 bytes from ElevenLabs for a single text chunk."""
    client = _get_client()
    url = f"{ELEVENLABS_STREAM_URL}?output_format=ulaw_8000&optimize_streaming_latency=3"
    payload = _make_payload(text)

    async with client.stream("POST", url, json=payload) as response:
        response.raise_for_status()
        async for chunk in response.aiter_bytes(chunk_size=640):
            if chunk:
                yield chunk


async def synthesize(text: str) -> bytes:
    """Synthesize text to raw ulaw 8kHz bytes (non-streaming, for short texts)."""
    client = _get_client()
    url = f"{ELEVENLABS_URL}?output_format=ulaw_8000"
    payload = _make_payload(text)
    response = await client.post(url, json=payload)
    response.raise_for_status()
    return response.content


async def synthesize_to_mulaw_chunks(text: str) -> AsyncGenerator[str, None]:
    """Synthesize text and yield base64 mulaw chunks ready for Twilio.
    
    Uses streaming API for low latency — audio starts playing before
    the full synthesis is complete.
    """
    sentences = _split_sentences(text)
    if not sentences:
        sentences = [text]

    for sentence in sentences:
        try:
            buffer = b""
            chunk_size = 640  # 640 bytes = 80ms of ulaw_8000

            async for raw_chunk in synthesize_stream(sentence):
                buffer += raw_chunk
                while len(buffer) >= chunk_size:
                    piece = buffer[:chunk_size]
                    buffer = buffer[chunk_size:]
                    yield base64.b64encode(piece).decode("ascii")

            # Flush remaining buffer
            if buffer:
                yield base64.b64encode(buffer).decode("ascii")

        except httpx.HTTPStatusError as e:
            logger.error(f"ElevenLabs HTTP {e.response.status_code}: {e.response.text[:200]}")
            # Fallback: try non-streaming
            try:
                raw = await synthesize(sentence)
                if raw:
                    for i in range(0, len(raw), chunk_size):
                        piece = raw[i:i + chunk_size]
                        if piece:
                            yield base64.b64encode(piece).decode("ascii")
            except Exception as e2:
                logger.error(f"ElevenLabs fallback also failed: {e2}")
        except Exception as e:
            logger.error(f"ElevenLabs TTS error ({type(e).__name__}): {e}")


async def synthesize_single_mulaw(text: str) -> AsyncGenerator[str, None]:
    """Quick synthesis for short acknowledgments — uses streaming for speed."""
    try:
        chunk_size = 640
        async for raw_chunk in synthesize_stream(text):
            yield base64.b64encode(raw_chunk).decode("ascii")
    except Exception as e:
        logger.error(f"ElevenLabs quick TTS error: {e}")


async def test_elevenlabs() -> dict:
    """Test ElevenLabs API."""
    try:
        data = await synthesize("Test.")
        return {"status": "ok", "voice_id": ELEVENLABS_VOICE_ID, "bytes": len(data)}
    except Exception as e:
        return {"status": "error", "error": f"{type(e).__name__}: {e}"}
