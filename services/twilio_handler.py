"""Twilio TwiML generation and media stream message builders.

Note: audioop/resampling is no longer needed since ElevenLabs outputs
ulaw_8000 natively — the exact format Twilio expects.
"""

from __future__ import annotations
import base64
import json

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


def build_media_message(audio_base64: str, stream_sid: str) -> str:
    return json.dumps({
        "event": "media",
        "streamSid": stream_sid,
        "media": {"payload": audio_base64},
    })


def build_mark_message(stream_sid: str, mark_name: str = "end") -> str:
    return json.dumps({
        "event": "mark",
        "streamSid": stream_sid,
        "mark": {"name": mark_name},
    })


def build_clear_message(stream_sid: str) -> str:
    return json.dumps({"event": "clear", "streamSid": stream_sid})
