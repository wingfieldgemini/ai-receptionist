"""Twilio TwiML generation and audio encoding/decoding."""

from __future__ import annotations
import base64
import json
import audioop

from config import SERVER_URL


def generate_twiml() -> str:
    """Return TwiML XML that starts a bidirectional media stream."""
    ws_url = SERVER_URL.replace("https://", "wss://").replace("http://", "ws://")
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Connect>
        <Stream url="{ws_url}/media-stream" />
    </Connect>
    <Pause length="3600"/>
</Response>"""


def resample_and_encode(pcm_bytes: bytes, from_rate: int = 16000, to_rate: int = 8000) -> str:
    """Resample PCM from source rate to 8kHz, then encode to base64 mulaw."""
    if from_rate != to_rate:
        pcm_8khz, _ = audioop.ratecv(pcm_bytes, 2, 1, from_rate, to_rate, None)
    else:
        pcm_8khz = pcm_bytes
    mulaw_bytes = audioop.lin2ulaw(pcm_8khz, 2)
    return base64.b64encode(mulaw_bytes).decode("ascii")


def build_media_message(audio_base64: str, stream_sid: str) -> str:
    return json.dumps({"event": "media", "streamSid": stream_sid, "media": {"payload": audio_base64}})


def build_mark_message(stream_sid: str, mark_name: str = "end") -> str:
    return json.dumps({"event": "mark", "streamSid": stream_sid, "mark": {"name": mark_name}})


def build_clear_message(stream_sid: str) -> str:
    return json.dumps({"event": "clear", "streamSid": stream_sid})
