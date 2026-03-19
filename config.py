"""Configuration loaded from environment variables."""

import os
import logging
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


def _require(key: str) -> str:
    val = os.getenv(key)
    if not val:
        raise RuntimeError(f"Missing required environment variable: {key}")
    return val


# Twilio
TWILIO_ACCOUNT_SID: str = _require("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN: str = _require("TWILIO_AUTH_TOKEN")
TWILIO_PHONE_NUMBER: str = os.getenv("TWILIO_PHONE_NUMBER", "")

# Deepgram
DEEPGRAM_API_KEY: str = _require("DEEPGRAM_API_KEY")

# OpenAI
OPENAI_API_KEY: str = _require("OPENAI_API_KEY")
OPENAI_MODEL: str = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
OPENAI_TEMPERATURE: float = float(os.getenv("OPENAI_TEMPERATURE", "0.7"))

# ElevenLabs
ELEVENLABS_API_KEY: str = _require("ELEVENLABS_API_KEY")
ELEVENLABS_VOICE_ID: str = os.getenv("ELEVENLABS_VOICE_ID", "EXAVITQu4vr4xnSDxMaL")
ELEVENLABS_MODEL: str = os.getenv("ELEVENLABS_MODEL", "eleven_multilingual_v2")

# Server
SERVER_URL: str = _require("SERVER_URL")
PORT: int = int(os.getenv("PORT", "8000"))

logger.info(f"Config loaded: MODEL={OPENAI_MODEL}, VOICE={ELEVENLABS_VOICE_ID}, SERVER={SERVER_URL}")
