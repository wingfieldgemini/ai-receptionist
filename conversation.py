"""Conversation state manager for each call."""

from __future__ import annotations
import time
import logging
from typing import Optional

from schemas import FicheDossier, ConversationMessage
from prompts import SOFIA_SYSTEM_PROMPT, FICHE_EXTRACTION_PROMPT

logger = logging.getLogger(__name__)


class Conversation:
    """Tracks the full state of a single phone call."""

    def __init__(self, call_sid: str):
        self.call_sid = call_sid
        self.stream_sid: Optional[str] = None
        self.start_time = time.time()
        self.flux: Optional[str] = None  # locataire / proprietaire / autre
        self.messages: list[ConversationMessage] = [
            ConversationMessage(role="system", content=SOFIA_SYSTEM_PROMPT)
        ]
        self.collected_data: dict = {}
        self.is_active = True
        self.is_speaking = False  # True while TTS audio is being sent

    @property
    def duration_seconds(self) -> float:
        return time.time() - self.start_time

    def add_user_message(self, text: str) -> None:
        self.messages.append(ConversationMessage(role="user", content=text))
        logger.info(f"[{self.call_sid}] CALLER: {text}")

    def add_assistant_message(self, text: str) -> None:
        self.messages.append(ConversationMessage(role="assistant", content=text))
        logger.info(f"[{self.call_sid}] SOFIA: {text}")

    def get_openai_messages(self) -> list[dict]:
        return [m.model_dump() for m in self.messages]

    def has_minimum_data(self) -> bool:
        """Check if we have at least prénom + téléphone from the conversation."""
        text = " ".join(m.content for m in self.messages if m.role == "user").lower()
        # Heuristic: if assistant asked for coordinates and user responded, likely collected
        has_name_exchange = any(
            "prénom" in m.content.lower() or "prénom" in m.content.lower()
            for m in self.messages
            if m.role == "assistant"
        )
        return has_name_exchange and len(self.messages) > 6

    async def extract_fiche(self) -> FicheDossier:
        """Ask OpenAI to extract a structured fiche from the conversation."""
        from services.openai_brain import extract_fiche
        
        conversation_text = "\n".join(
            f"{'Sofia' if m.role == 'assistant' else 'Appelant' if m.role == 'user' else 'System'}: {m.content}"
            for m in self.messages
            if m.role != "system"
        )
        
        fiche_dict = await extract_fiche(conversation_text)
        try:
            return FicheDossier(**fiche_dict)
        except Exception as e:
            logger.error(f"[{self.call_sid}] Failed to parse fiche: {e}")
            return FicheDossier()
