"""ElevenLabs text-to-speech with resampling to 8kHz mulaw for Twilio."""

from __future__ import annotations
import re
import logging
from typing import AsyncGenerator

import httpx

from config import ELEVENLABS_API_KEY, ELEVENLABS_VOICE_ID, ELEVENLABS_MODEL
from services.twilio_handler import resample_and_encode

logger = logging.getLogger(__name__)

ELEVENLABS_URL = f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVENLABS_VOICE_ID}"

# Chunk size for sending audio to Twilio (in base64-encoded mulaw bytes)
# Twilio expects chunks — we send ~20ms frames (160 bytes of mulaw = 20ms at 8kHz)
TWILIO_AUDIO_CHUNK_SIZE = 640  # 80ms of mulaw at 8kHz


def _split_sentences(text: str) -> list[str]:
    """Split text into sentences for chunked TTS."""
    sentences = re.split(r'(?<=[.!?])\s+', text)
    return [s.strip() for s in sentences if s.strip()]


async def synthesize(text: str) -> bytes:
    """Synthesize text to PCM 16kHz audio bytes via ElevenLabs."""
    headers = {
        "xi-api-key": ELEVENLABS_API_KEY,
        "Content-Type": "application/json",
        "Accept": "audio/wav",
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

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            ELEVENLABS_URL,
            headers=headers,
            json=payload,
        )
        response.raise_for_status()
        wav_data = response.content
    
    # Skip WAV header (44 bytes) to get raw PCM
    # ElevenLabs returns PCM 16-bit mono when Accept: audio/wav
    pcm_data = wav_data[44:] if len(wav_data) > 44 else wav_data
    return pcm_data


async def synthesize_to_mulaw_chunks(text: str) -> AsyncGenerator[str, None]:
    """Synthesize text and yield base64 mulaw chunks ready for Twilio.
    
    Splits long text into sentences, synthesizes each, resamples to 8kHz mulaw,
    and yields base64-encoded chunks suitable for Twilio media messages.
    """
    sentences = _split_sentences(text)
    if not sentences:
        sentences = [text]

    for sentence in sentences:
        try:
            pcm_16khz = await synthesize(sentence)
            if not pcm_16khz:
                continue
                
            # Resample from 16kHz to 8kHz mulaw and base64 encode
            mulaw_b64 = resample_and_encode(pcm_16khz, from_rate=16000, to_rate=8000)
            
            # Split into Twilio-sized chunks
            # Each chunk should be ~20ms of audio for smooth playback
            # 8kHz mulaw = 8000 bytes/sec, 20ms = 160 bytes = ~216 base64 chars
            chunk_b64_size = 1280  # ~640 bytes mulaw = 80ms
            for i in range(0, len(mulaw_b64), chunk_b64_size):
                chunk = mulaw_b64[i:i + chunk_b64_size]
                if chunk:
                    yield chunk
                    
        except httpx.HTTPStatusError as e:
            logger.error(f"ElevenLabs HTTP error: {e.response.status_code} - {e.response.text[:200]}")
        except Exception as e:
            logger.error(f"ElevenLabs TTS error: {e}")
