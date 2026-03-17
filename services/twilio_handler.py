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
    <Say language="fr-FR">Veuillez patienter, connexion en cours.</Say>
    <Connect>
        <Stream url="{ws_url}/media-stream" />
    </Connect>
    <Say language="fr-FR">Merci d'avoir appelé. Au revoir.</Say>
</Response>"""


def decode_mulaw_to_pcm16(base64_payload: str) -> bytes:
    """Decode Twilio base64 mulaw audio to 16-bit PCM at 8kHz."""
    mulaw_bytes = base64.b64decode(base64_payload)
    return audioop.ulaw2lin(mulaw_bytes, 2)


def encode_pcm16_to_mulaw_base64(pcm_data: bytes) -> str:
    """Encode 16-bit PCM audio to base64 mulaw."""
    mulaw_bytes = audioop.lin2ulaw(pcm_data, 2)
    return base64.b64encode(mulaw_bytes).decode("ascii")


def resample_and_encode(pcm_16khz: bytes, from_rate: int = 16000, to_rate: int = 8000) -> str:
    """Resample PCM from source rate to 8kHz, then encode to base64 mulaw."""
    if from_rate != to_rate:
        pcm_8khz, _ = audioop.ratecv(pcm_16khz, 2, 1, from_rate, to_rate, None)
    else:
        pcm_8khz = pcm_16khz
    return encode_pcm16_to_mulaw_base64(pcm_8khz)


def build_media_message(audio_base64: str, stream_sid: str) -> str:
    """Build a JSON message to send audio back via Twilio WebSocket."""
    return json.dumps({
        "event": "media",
        "streamSid": stream_sid,
        "media": {
            "payload": audio_base64
        }
    })


def build_mark_message(stream_sid: str, mark_name: str = "end") -> str:
    """Build a mark message to track when audio finishes playing."""
    return json.dumps({
        "event": "mark",
        "streamSid": stream_sid,
        "mark": {
            "name": mark_name
        }
    })


def build_clear_message(stream_sid: str) -> str:
    """Build a clear message to stop any queued audio."""
    return json.dumps({
        "event": "clear",
        "streamSid": stream_sid
    })
