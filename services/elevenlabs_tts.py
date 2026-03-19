"""ElevenLabs text-to-speech with resampling to 8kHz mulaw for Twilio."""

from __future__ import annotations
import re
import struct
import logging
from typing import AsyncGenerator

import httpx

from config import ELEVENLABS_API_KEY, ELEVENLABS_VOICE_ID, ELEVENLABS_MODEL
from services.twilio_handler import resample_and_encode

logger = logging.getLogger(__name__)

ELEVENLABS_URL = f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVENLABS_VOICE_ID}"


def _split_sentences(text: str) -> list[str]:
    """Split text into sentences for chunked TTS."""
    sentences = re.split(r'(?<=[.!?])\s+', text)
    return [s.strip() for s in sentences if s.strip()]


def _strip_wav_header(wav_data: bytes) -> bytes:
    """Properly parse WAV header to extract raw PCM data."""
    if len(wav_data) < 12:
        return wav_data
    
    if wav_data[:4] != b'RIFF' or wav_data[8:12] != b'WAVE':
        logger.warning("Not a valid WAV file, returning raw data")
        return wav_data
    
    offset = 12
    while offset < len(wav_data) - 8:
        chunk_id = wav_data[offset:offset + 4]
        chunk_size = struct.unpack('<I', wav_data[offset + 4:offset + 8])[0]
        
        if chunk_id == b'data':
            pcm_start = offset + 8
            pcm_data = wav_data[pcm_start:pcm_start + chunk_size]
            if len(pcm_data) % 2 != 0:
                pcm_data = pcm_data[:-1]
            return pcm_data
        
        offset += 8 + chunk_size
        if chunk_size % 2 != 0:
            offset += 1
    
    logger.warning("Could not find 'data' chunk, falling back to 44-byte skip")
    pcm_data = wav_data[44:]
    if len(pcm_data) % 2 != 0:
        pcm_data = pcm_data[:-1]
    return pcm_data


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
    
    pcm_data = _strip_wav_header(wav_data)
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
            logger.error(f"ElevenLabs HTTP error: {e.response.status_code} - {e.response.text[:200]}")
        except Exception as e:
            logger.error(f"ElevenLabs TTS error: {e}")
