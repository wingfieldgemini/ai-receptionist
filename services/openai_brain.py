"""OpenAI GPT-4o-mini chat completions for conversation and fiche extraction."""

from __future__ import annotations
import json
import logging

from openai import AsyncOpenAI

from config import OPENAI_API_KEY, OPENAI_MODEL, OPENAI_TEMPERATURE
from prompts import FICHE_EXTRACTION_PROMPT

logger = logging.getLogger(__name__)

client = AsyncOpenAI(api_key=OPENAI_API_KEY)


async def get_response(messages: list[dict]) -> str:
    """Get a conversational response from OpenAI given the full message history."""
    try:
        response = await client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=messages,
            temperature=OPENAI_TEMPERATURE,
            max_tokens=300,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        logger.error(f"OpenAI error: {e}")
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
        # Strip markdown code fences if present
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
        logger.error(f"OpenAI fiche extraction error: {e}")
        return {}
