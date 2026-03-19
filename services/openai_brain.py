"""OpenAI GPT-4o-mini chat completions for conversation and fiche extraction."""

from __future__ import annotations
import json
import logging
import traceback

from openai import AsyncOpenAI

from config import OPENAI_API_KEY, OPENAI_MODEL, OPENAI_TEMPERATURE
from prompts import FICHE_EXTRACTION_PROMPT

logger = logging.getLogger(__name__)

client = AsyncOpenAI(api_key=OPENAI_API_KEY)


async def get_response(messages: list[dict]) -> str:
    """Get a conversational response from OpenAI given the full message history."""
    try:
        logger.info(f"OpenAI request: model={OPENAI_MODEL}, messages={len(messages)}")
        response = await client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=messages,
            temperature=OPENAI_TEMPERATURE,
            max_tokens=300,
        )
        result = response.choices[0].message.content.strip()
        logger.info(f"OpenAI response: {result[:100]}")
        return result
    except Exception as e:
        logger.error(f"OpenAI error ({type(e).__name__}): {e}")
        logger.error(f"OpenAI traceback: {traceback.format_exc()}")
        return "Excusez-moi, j'ai un petit souci technique. Pouvez-vous répéter ?"


async def extract_fiche(conversation_text: str) -> dict:
    """Extract structured fiche dossier JSON from conversation text."""
    try:
        response = await client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": FICHE_EXTRACTION_PROMPT},
                {"role": "user", "content": conversation_text},
            ],
            temperature=0.1,
            max_tokens=800,
        )
        raw = response.choices[0].message.content.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
            if raw.endswith("```"):
                raw = raw[:-3]
            raw = raw.strip()
        return json.loads(raw)
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse fiche JSON: {e}")
        return {}
    except Exception as e:
        logger.error(f"OpenAI fiche error ({type(e).__name__}): {e}")
        return {}


async def test_openai() -> dict:
    """Test OpenAI API connectivity."""
    try:
        response = await client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[{"role": "user", "content": "Say OK"}],
            max_tokens=5,
        )
        return {"status": "ok", "model": OPENAI_MODEL, "response": response.choices[0].message.content.strip()}
    except Exception as e:
        return {"status": "error", "model": OPENAI_MODEL, "error": f"{type(e).__name__}: {e}"}
