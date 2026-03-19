"""Real-time Deepgram speech-to-text via WebSocket."""

from __future__ import annotations
import asyncio
import json
import logging
from typing import AsyncGenerator

import websockets

from config import DEEPGRAM_API_KEY

logger = logging.getLogger(__name__)

DEEPGRAM_WS_URL = "wss://api.deepgram.com/v1/listen"
DEEPGRAM_PARAMS = {
    "model": "nova-2",
    "language": "fr",
    "encoding": "mulaw",
    "sample_rate": "8000",
    "channels": "1",
    "endpointing": "300",
    "interim_results": "true",
    "utterance_end_ms": "1000",
}


class DeepgramSTT:
    def __init__(self, call_sid: str):
        self.call_sid = call_sid
        self._ws = None
        self._keepalive_task = None

    async def connect(self) -> None:
        params = "&".join(f"{k}={v}" for k, v in DEEPGRAM_PARAMS.items())
        url = f"{DEEPGRAM_WS_URL}?{params}"
        headers = {"Authorization": f"Token {DEEPGRAM_API_KEY}"}
        self._ws = await websockets.connect(url, additional_headers=headers)
        self._keepalive_task = asyncio.create_task(self._keepalive())
        logger.info(f"[{self.call_sid}] Deepgram STT connected")

    async def _keepalive(self) -> None:
        """Send keepalive messages every 8 seconds to prevent Deepgram timeout."""
        try:
            while self._ws:
                await asyncio.sleep(8)
                if self._ws:
                    try:
                        await self._ws.send(json.dumps({"type": "KeepAlive"}))
                    except Exception:
                        break
        except asyncio.CancelledError:
            pass

    async def send_audio(self, audio_bytes: bytes) -> None:
        if self._ws:
            try:
                await self._ws.send(audio_bytes)
            except Exception as e:
                logger.warning(f"[{self.call_sid}] Deepgram send error: {e}")

    async def receive_transcripts(self) -> AsyncGenerator[str, None]:
        if not self._ws:
            return
        try:
            async for raw_msg in self._ws:
                try:
                    msg = json.loads(raw_msg)
                except json.JSONDecodeError:
                    continue

                if msg.get("type") == "Results":
                    alternatives = msg.get("channel", {}).get("alternatives", [])
                    if not alternatives:
                        continue
                    transcript = alternatives[0].get("transcript", "").strip()
                    is_final = msg.get("is_final", False)
                    if is_final and transcript:
                        logger.info(f"[{self.call_sid}] STT: {transcript}")
                        yield transcript

        except websockets.exceptions.ConnectionClosed:
            logger.info(f"[{self.call_sid}] Deepgram closed")
        except Exception as e:
            logger.error(f"[{self.call_sid}] Deepgram error ({type(e).__name__}): {e}")

    async def close(self) -> None:
        if self._keepalive_task:
            self._keepalive_task.cancel()
            try:
                await self._keepalive_task
            except asyncio.CancelledError:
                pass
            self._keepalive_task = None

        if self._ws:
            try:
                await self._ws.send(json.dumps({"type": "CloseStream"}))
                await self._ws.close()
            except Exception:
                pass
            self._ws = None
            logger.info(f"[{self.call_sid}] Deepgram disconnected")


async def test_deepgram() -> dict:
    try:
        params = "&".join(f"{k}={v}" for k, v in DEEPGRAM_PARAMS.items())
        url = f"{DEEPGRAM_WS_URL}?{params}"
        headers = {"Authorization": f"Token {DEEPGRAM_API_KEY}"}
        ws = await websockets.connect(url, additional_headers=headers)
        await ws.send(json.dumps({"type": "CloseStream"}))
        await ws.close()
        return {"status": "ok"}
    except Exception as e:
        return {"status": "error", "error": f"{type(e).__name__}: {e}"}
