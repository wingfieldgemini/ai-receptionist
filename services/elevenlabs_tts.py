"""ElevenLabs text-to-speech — raw PCM 16kHz, resampled to 8kHz mulaw for Twilio."""

from __future__ import annotations
import re
import logging
from typing import AsyncGenerator

import httpx

from config import ELEVENLABS_API_KEY, ELEVENLABS_VOICE_ID, ELEVENLABS_MODEL
from services.twilio_handler import resample_and_encode

logger = logging.getLogger(__name__)

ELEVENLABS_URL = f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVENLABS_VOICE_ID}"


def _split_sentences(text: str) -> list[str]:
    sentences = re.split(r'(?<=[.!?])\s+', text)
    return [s.strip() for s in sentences if s.strip()]


async def synthesize(text: str) -> bytes:
    """Synthesize text to raw PCM 16kHz 16-bit mono via ElevenLabs."""
    headers = {
        "xi-api-key": ELEVENLABS_API_KEY,
        "Content-Type": "application/json",
    }
    payload = {
        "text": text,
        "model_id": ELEVENLABS_MODEL,
        "voice_settings": {
            "stability": 0.5,
            "similarity_boost": 0.75,
            "style": 0.0,
            "use_speaker_boost": True,
        },
    }
    url = f"{ELEVENLABS_URL}?output_format=pcm_16000"

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(url, headers=headers, json=payload)
        response.raise_for_status()
        pcm_data = response.content

    if len(pcm_data) % 2 != 0:
        pcm_data = pcm_data[:-1]

    logger.info(f"ElevenLabs: {len(pcm_data)} bytes for '{text[:50]}'")
    return pcm_data


async def synthesize_to_mulaw_chunks(text: str) -> AsyncGenerator[str, None]:
    """Synthesize text and yield base64 mulaw chunks ready for Twilio."""
    sentences = _split_sentences(text)
    if not sentences:
        sentences = [text]

    for sentence in sentences:
        try:
            pcm_16khz = await synthesize(sentence)
            if not pcm_16khz:
                continue

            mulaw_b64 = resample_and_encode(pcm_16khz, from_rate=16000, to_rate=8000)

            chunk_b64_size = 1280
            for i in range(0, len(mulaw_b64), chunk_b64_size):
                chunk = mulaw_b64[i:i + chunk_b64_size]
                if chunk:
                    yield chunk

        except httpx.HTTPStatusError as e:
            logger.error(f"ElevenLabs HTTP {e.response.status_code}: {e.response.text[:200]}")
        except Exception as e:
            logger.error(f"ElevenLabs TTS error ({type(e).__name__}): {e}")


async def test_elevenlabs() -> dict:
    """Test ElevenLabs API."""
    try:
        pcm = await synthesize("Test.")
        return {"status": "ok", "voice_id": ELEVENLABS_VOICE_ID, "bytes": len(pcm)}
    except Exception as e:
        return {"status": "error", "error": f"{type(e).__name__}: {e}"}
