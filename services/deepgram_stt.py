"""Real-time Deepgram speech-to-text via WebSocket."""

from __future__ import annotations
import json
import logging
from typing import AsyncGenerator, Optional

import websockets
from websockets.asyncio.client import ClientConnection

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
    """Manages a streaming WebSocket connection to Deepgram."""

    def __init__(self, call_sid: str):
        self.call_sid = call_sid
        self._ws: Optional[ClientConnection] = None

    async def connect(self) -> None:
        """Open WebSocket connection to Deepgram."""
        params = "&".join(f"{k}={v}" for k, v in DEEPGRAM_PARAMS.items())
        url = f"{DEEPGRAM_WS_URL}?{params}"
        headers = {"Authorization": f"Token {DEEPGRAM_API_KEY}"}
        self._ws = await websockets.connect(url, additional_headers=headers)
        logger.info(f"[{self.call_sid}] Deepgram STT connected")

    async def send_audio(self, audio_bytes: bytes) -> None:
        """Forward raw audio bytes to Deepgram."""
        if self._ws:
            try:
                await self._ws.send(audio_bytes)
            except Exception as e:
                logger.warning(f"[{self.call_sid}] Deepgram send error: {e}")

    async def receive_transcripts(self) -> AsyncGenerator[str, None]:
        """Yield final transcript strings from Deepgram."""
        if not self._ws:
            return
        try:
            async for raw_msg in self._ws:
                try:
                    msg = json.loads(raw_msg)
                except json.JSONDecodeError:
                    continue

                # Check for final transcripts
                if msg.get("type") == "Results":
                    channel = msg.get("channel", {})
                    alternatives = channel.get("alternatives", [])
                    if not alternatives:
                        continue
                    transcript = alternatives[0].get("transcript", "").strip()
                    is_final = msg.get("is_final", False)
                    
                    if is_final and transcript:
                        yield transcript
                        
                # Handle utterance end
                elif msg.get("type") == "UtteranceEnd":
                    pass  # Handled by is_final above

        except websockets.exceptions.ConnectionClosed:
            logger.info(f"[{self.call_sid}] Deepgram connection closed")
        except Exception as e:
            logger.error(f"[{self.call_sid}] Deepgram receive error: {e}")

    async def close(self) -> None:
        """Close the Deepgram WebSocket connection."""
        if self._ws:
            try:
                # Send close message to Deepgram
                await self._ws.send(json.dumps({"type": "CloseStream"}))
                await self._ws.close()
            except Exception:
                pass
            self._ws = None
            logger.info(f"[{self.call_sid}] Deepgram STT disconnected")
