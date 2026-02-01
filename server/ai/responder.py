"""AI Responder - generates contextual responses using OpenAI."""
import logging
from dataclasses import dataclass
from typing import Optional

from openai import AsyncOpenAI

from server.config import get_settings
from server.constants import WAKE_WORDS, BOT_NAME

logger = logging.getLogger(__name__)

SYSTEM_PROMPT_WITH_CONTEXT = """You are "Recall", a friendly project bot that recalls information from past meetings.

CRITICAL RULES:
1. ONLY use information from the "MEETING CONTEXT" section below
2. NEVER invent or fabricate meeting details, dates, names, or discussions
3. If context doesn't contain relevant info, say "I don't have information about that in my meeting records"
4. Always cite the meeting title and date when referencing information
5. Keep responses to 1-2 sentences - you're speaking in a live meeting

Your name is Recall. Speak in a friendly, helpful tone."""

SYSTEM_PROMPT_NO_CONTEXT = """You are "Recall", a friendly project bot that recalls information from past meetings.

CRITICAL RULES:
1. You have NO relevant context from past meetings for this query
2. NEVER invent or fabricate meeting details, dates, names, or discussions
3. Say something like: "I don't have any relevant information from past meetings about that topic"
4. Keep responses to 1 sentence

Your name is Recall. Speak in a friendly, helpful tone."""

GREETING_PROMPT = """You are "Recall", a friendly project bot.
Introduce yourself in ONE short sentence. Mention that people can get your attention by saying "Recall".
Do NOT mention any specific meetings or dates."""


@dataclass
class AIResponse:
    """Response containing text and optional audio."""
    text: str
    audio: Optional[bytes] = None


class AIResponder:
    """Generates AI responses with TTS."""

    def __init__(self):
        self._settings = get_settings()
        self._client = AsyncOpenAI(api_key=self._settings.openai_api_key)
        self._conversation: list[dict] = []
        self._context: str = ""
        self._action_items: str = ""
        self._awaiting_question: bool = False

    def set_context(self, context: str) -> None:
        """Set RAG context for the next response."""
        self._context = context

    def set_action_items_context(self, context: str) -> None:
        """Set action items to mention at meeting start."""
        self._action_items = context

    def get_recent_context(self) -> str:
        """Get recent conversation for follow-up query expansion."""
        if not self._conversation:
            return ""
        recent = self._conversation[-4:]
        return " ".join(msg.get("content", "") for msg in recent)

    def add_user_message(self, speaker: str, text: str) -> None:
        """Add user utterance to conversation history."""
        self._conversation.append({
            "role": "user",
            "content": f"[{speaker}]: {text}"
        })
        if len(self._conversation) > 20:
            self._conversation = self._conversation[-20:]

    async def should_respond(self, text: str) -> bool:
        """Determine if the bot should respond to this utterance."""
        text_lower = text.lower().strip()

        # Check for follow-up after wake word
        if self._awaiting_question:
            self._awaiting_question = False
            if len(text_lower) > 3:
                return True

        # Check for wake word
        has_wake_word = any(wake in text_lower for wake in WAKE_WORDS)
        if not has_wake_word:
            return False

        # Check if just wake word or wake word + question
        remaining = text_lower
        for wake in WAKE_WORDS:
            remaining = remaining.replace(wake, "").strip()
        for filler in [",", ".", "hey", "ok", "okay", "um", "uh"]:
            remaining = remaining.replace(filler, "").strip()

        if len(remaining) < 5:
            self._awaiting_question = True
            return True

        return True

    def is_awaiting_question(self) -> bool:
        """Check if bot is waiting for a follow-up question."""
        return self._awaiting_question

    def clear_awaiting(self) -> None:
        """Clear the awaiting flag."""
        self._awaiting_question = False

    async def generate_response(self, include_audio: bool = True) -> AIResponse:
        """Generate response based on conversation history and context."""
        try:
            if self._context:
                system_content = SYSTEM_PROMPT_WITH_CONTEXT
                system_content += f"\n\n=== MEETING CONTEXT ===\n{self._context}\n=== END CONTEXT ==="
            else:
                system_content = SYSTEM_PROMPT_NO_CONTEXT

            if self._action_items:
                system_content += f"\n\nPending action items:\n{self._action_items}"

            messages = [{"role": "system", "content": system_content}]
            messages.extend(self._conversation)

            response = await self._client.chat.completions.create(
                model="gpt-4o-mini",
                messages=messages,
                max_tokens=150,
                temperature=0.3,
            )

            text = response.choices[0].message.content
            self._conversation.append({"role": "assistant", "content": text})
            self._context = ""

            audio = None
            if include_audio:
                audio = await self._generate_tts(text)

            return AIResponse(text=text, audio=audio)

        except Exception as e:
            logger.error(f"Response generation error: {e}")
            return AIResponse(text="I'm sorry, I encountered an error.")

    async def generate_greeting(self, has_action_items: bool = False) -> AIResponse:
        """Generate initial greeting."""
        try:
            system_content = GREETING_PROMPT
            if has_action_items:
                system_content += "\nMention that you have some pending action items to share."

            messages = [
                {"role": "system", "content": system_content},
                {"role": "user", "content": "Please introduce yourself."}
            ]

            response = await self._client.chat.completions.create(
                model="gpt-4o-mini",
                messages=messages,
                max_tokens=60,
                temperature=0.3,
            )

            text = response.choices[0].message.content
            self._conversation.append({"role": "assistant", "content": text})

            audio = await self._generate_tts(text)
            return AIResponse(text=text, audio=audio)

        except Exception as e:
            logger.error(f"Greeting error: {e}")
            return AIResponse(text="Hello, I'm Recall, your meeting memory assistant.")

    async def _generate_tts(self, text: str) -> Optional[bytes]:
        """Convert text to speech using OpenAI TTS."""
        try:
            response = await self._client.audio.speech.create(
                model="tts-1",
                voice="alloy",
                input=text,
                response_format="mp3",
            )
            return response.content
        except Exception as e:
            logger.error(f"TTS error: {e}")
            return None
