"""OpenAI GPT-4o-mini — streaming + non-streaming chat completions."""

from __future__ import annotations
import json
import re
import logging
import traceback
from typing import AsyncGenerator

from openai import AsyncOpenAI

from config import OPENAI_API_KEY, OPENAI_MODEL, OPENAI_TEMPERATURE
from prompts import FICHE_EXTRACTION_PROMPT

logger = logging.getLogger(__name__)

client = AsyncOpenAI(api_key=OPENAI_API_KEY)

# Sentence-ending pattern for streaming sentence detection
_SENTENCE_END = re.compile(r'[.!?]\s*$')


async def get_response(messages: list[dict]) -> str:
    """Get a conversational response from OpenAI (non-streaming)."""
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
        return "Excusez-moi, j'ai un petit souci technique. Pouvez-vous répéter ?"


async def get_response_streaming(messages: list[dict]) -> AsyncGenerator[str, None]:
    """Stream OpenAI response, yielding complete sentences as they form.
    
    This allows TTS to begin on the first sentence while OpenAI is still
    generating the rest of the response. Typically saves 1-2 seconds.
    """
    try:
        logger.info(f"OpenAI streaming: model={OPENAI_MODEL}, messages={len(messages)}")
        stream = await client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=messages,
            temperature=OPENAI_TEMPERATURE,
            max_tokens=300,
            stream=True,
        )

        buffer = ""
        async for chunk in stream:
            delta = chunk.choices[0].delta
            if delta.content:
                buffer += delta.content

                # Check if we have a complete sentence
                # Look for sentence-ending punctuation followed by space or end
                while True:
                    match = re.search(r'([.!?])\s+', buffer)
                    if match:
                        # Yield everything up to and including the punctuation
                        end_pos = match.start() + 1
                        sentence = buffer[:end_pos].strip()
                        buffer = buffer[match.end():]
                        if sentence:
                            logger.info(f"OpenAI sentence: {sentence[:80]}")
                            yield sentence
                    else:
                        break

        # Yield any remaining text
        if buffer.strip():
            logger.info(f"OpenAI final: {buffer.strip()[:80]}")
            yield buffer.strip()

    except Exception as e:
        logger.error(f"OpenAI streaming error ({type(e).__name__}): {e}")
        logger.error(traceback.format_exc())
        yield "Excusez-moi, j'ai un petit souci technique. Pouvez-vous répéter ?"


async def get_full_streaming_response(messages: list[dict]) -> tuple[str, AsyncGenerator[str, None]]:
    """Returns the generator and collects full text for conversation history.
    
    Usage:
        sentences = []
        async for sentence in get_response_streaming(messages):
            sentences.append(sentence)
            # Start TTS for this sentence
        full_response = " ".join(sentences)
    """
    # Just use get_response_streaming directly
    pass


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
