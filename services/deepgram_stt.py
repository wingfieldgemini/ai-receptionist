"""Real-time Deepgram speech-to-text via WebSocket."""

from __future__ import annotations
import asyncio
import json
import logging
import time
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
    "endpointing": "250",
    "interim_results": "true",
    "utterance_end_ms": "800",
}

# Keepalive interval — Deepgram disconnects after ~10s of no messages
KEEPALIVE_INTERVAL = 3  # seconds (docs recommend 3-5s)


class DeepgramSTT:
    def __init__(self, call_sid: str):
        self.call_sid = call_sid
        self._ws = None
        self._keepalive_task = None
        self._connected = False
        self._closing = False
        self._last_audio_time = 0.0
        self._reconnect_count = 0
        self._max_reconnects = 10  # More generous reconnect limit

    def _build_url(self) -> str:
        params = "&".join(f"{k}={v}" for k, v in DEEPGRAM_PARAMS.items())
        return f"{DEEPGRAM_WS_URL}?{params}"

    async def connect(self) -> None:
        url = self._build_url()
        headers = {"Authorization": f"Token {DEEPGRAM_API_KEY}"}
        try:
            self._ws = await websockets.connect(
                url,
                additional_headers=headers,
            )
            self._connected = True
            self._closing = False
            self._keepalive_task = asyncio.create_task(self._keepalive_loop())
            logger.info(f"[{self.call_sid}] Deepgram STT connected")
        except Exception as e:
            logger.error(f"[{self.call_sid}] Deepgram connect failed: {e}")
            self._connected = False
            raise

    async def _reconnect(self) -> bool:
        """Try to reconnect to Deepgram. Returns True if successful."""
        if self._closing:
            return False

        self._reconnect_count += 1
        if self._reconnect_count > self._max_reconnects:
            logger.warning(f"[{self.call_sid}] Deepgram max reconnects ({self._max_reconnects}) reached")
            return False

        logger.info(f"[{self.call_sid}] Deepgram reconnect attempt {self._reconnect_count}...")

        # Cancel old keepalive
        if self._keepalive_task:
            self._keepalive_task.cancel()
            try:
                await self._keepalive_task
            except asyncio.CancelledError:
                pass

        # Close old connection
        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass

        # Exponential backoff: 0.5s, 1s, 2s, 4s... capped at 5s
        delay = min(0.5 * (2 ** (self._reconnect_count - 1)), 5.0)
        await asyncio.sleep(delay)

        try:
            await self.connect()
            self._reconnect_count = 0  # Reset on success
            return True
        except Exception as e:
            logger.error(f"[{self.call_sid}] Deepgram reconnect failed: {e}")
            self._connected = False
            return False

    async def _keepalive_loop(self) -> None:
        """Send KeepAlive messages every few seconds to prevent Deepgram timeout.
        
        CRITICAL: Deepgram disconnects after ~10s with no messages.
        KeepAlive must be sent as a TEXT WebSocket frame (not binary).
        """
        keepalive_msg = json.dumps({"type": "KeepAlive"})
        try:
            while self._ws and self._connected and not self._closing:
                await asyncio.sleep(KEEPALIVE_INTERVAL)
                if self._ws and self._connected and not self._closing:
                    try:
                        # Explicitly send as text frame
                        await self._ws.send(keepalive_msg)
                        logger.debug(f"[{self.call_sid}] Deepgram keepalive sent")
                    except websockets.exceptions.ConnectionClosed:
                        logger.warning(f"[{self.call_sid}] Deepgram keepalive: connection closed")
                        self._connected = False
                        break
                    except Exception as e:
                        logger.warning(f"[{self.call_sid}] Deepgram keepalive error: {e}")
                        self._connected = False
                        break
        except asyncio.CancelledError:
            pass

    async def send_audio(self, audio_bytes: bytes) -> None:
        """Send audio data to Deepgram. This also serves as keepalive."""
        if not self._ws or not self._connected:
            return
        try:
            await self._ws.send(audio_bytes)
            self._last_audio_time = time.time()
        except websockets.exceptions.ConnectionClosed:
            logger.warning(f"[{self.call_sid}] Deepgram send: connection closed")
            self._connected = False
        except Exception as e:
            logger.warning(f"[{self.call_sid}] Deepgram send error: {e}")
            self._connected = False

    async def receive_transcripts(self) -> AsyncGenerator[str, None]:
        """Yield final transcripts, auto-reconnecting if Deepgram drops."""
        while not self._closing:
            if not self._ws or not self._connected:
                if not await self._reconnect():
                    await asyncio.sleep(1)
                    continue

            try:
                async for raw_msg in self._ws:
                    if self._closing:
                        return

                    try:
                        msg = json.loads(raw_msg)
                    except json.JSONDecodeError:
                        continue

                    msg_type = msg.get("type")

                    if msg_type == "Results":
                        alternatives = msg.get("channel", {}).get("alternatives", [])
                        if not alternatives:
                            continue
                        transcript = alternatives[0].get("transcript", "").strip()
                        is_final = msg.get("is_final", False)
                        speech_final = msg.get("speech_final", False)

                        if is_final and transcript:
                            logger.info(f"[{self.call_sid}] STT: {transcript}")
                            yield transcript

                    elif msg_type == "UtteranceEnd":
                        logger.debug(f"[{self.call_sid}] Deepgram: utterance end")

                    elif msg_type == "SpeechStarted":
                        logger.debug(f"[{self.call_sid}] Deepgram: speech started")

                    elif msg_type == "Metadata":
                        logger.debug(f"[{self.call_sid}] Deepgram metadata received")

                # WebSocket closed normally
                logger.info(f"[{self.call_sid}] Deepgram stream ended normally")
                self._connected = False

            except websockets.exceptions.ConnectionClosed as e:
                logger.warning(f"[{self.call_sid}] Deepgram closed (code={e.code}, reason={e.reason})")
                self._connected = False
            except asyncio.CancelledError:
                return
            except Exception as e:
                logger.error(f"[{self.call_sid}] Deepgram error ({type(e).__name__}): {e}")
                self._connected = False

    async def close(self) -> None:
        """Gracefully close the Deepgram connection."""
        self._closing = True
        self._connected = False

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
            logger.info(f"[{self.call_sid}] Deepgram disconnected cleanly")


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
