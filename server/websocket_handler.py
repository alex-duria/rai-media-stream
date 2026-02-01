"""WebSocket handler for the output media page."""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import time
from dataclasses import dataclass, field
from collections import deque
from typing import Optional

from fastapi import WebSocket, WebSocketDisconnect

from server.constants import RESPONSE_DELAY_SEC, LEAVE_KEYWORDS, WAKE_WORDS
from server.models import WSMessageType
from server.ai.responder import AIResponder
from server.rag.engine import get_rag_engine, RAGEngine

logger = logging.getLogger(__name__)


@dataclass
class SessionState:
    """Per-connection session state."""
    project_id: str
    recurring_meeting_id: Optional[str] = None
    bot_id: Optional[str] = None
    utterances: deque = field(default_factory=lambda: deque(maxlen=10))
    is_processing: bool = False
    last_utterance_time: float = 0.0
    pending_response: bool = False


class OutputMediaHandler:
    """Handles a single output media WebSocket connection."""

    __slots__ = ("_ws", "_state", "_rag", "_ai", "_lock")

    def __init__(
        self,
        websocket: WebSocket,
        project_id: str,
        recurring_meeting_id: Optional[str] = None,
        bot_id: Optional[str] = None,
    ):
        self._ws = websocket
        self._state = SessionState(
            project_id=project_id,
            recurring_meeting_id=recurring_meeting_id,
            bot_id=bot_id,
        )
        self._rag: RAGEngine | None = get_rag_engine(recurring_meeting_id)
        self._ai = AIResponder()
        self._lock = asyncio.Lock()

    async def handle(self) -> None:
        """Main connection handler."""
        await self._ws.accept()

        try:
            if self._rag:
                await self._rag.sync_index()
                action_context = self._rag.get_action_items_context()
                if action_context:
                    self._ai.set_action_items_context(action_context)

            await self._send_status("connected", "Recall connected")
            await self._send_greeting()
            await self._receive_loop()

        except WebSocketDisconnect:
            pass
        except Exception as e:
            logger.exception(f"WebSocket error: {e}")
            await self._send_error(str(e))

    async def receive_transcript(self, speaker: str, text: str, is_final: bool) -> None:
        """Process incoming transcript from client."""
        self._state.utterances.append(text)
        self._ai.add_user_message(speaker, text)

        if not is_final:
            return

        if await self._check_voice_commands(text, speaker):
            return

        self._state.last_utterance_time = time.time()

        if await self._ai.should_respond(text):
            if self._ai.is_awaiting_question():
                await self._send_wake_confirmation()
            else:
                self._state.pending_response = True
                asyncio.create_task(self._delayed_response_check())

    async def _send_wake_confirmation(self) -> None:
        """Send 'Yes?' confirmation when user says just the wake word."""
        await self._send_message(WSMessageType.TRANSCRIPT, {
            "speaker": "assistant",
            "text": "Yes?",
            "is_final": True,
        })

        try:
            audio = await self._ai._generate_tts("Yes?")
            if audio:
                await self._send_audio(audio)
        except Exception as e:
            logger.error(f"TTS error: {e}")

    async def _check_voice_commands(self, text: str, speaker: str) -> bool:
        """Check for voice commands. Returns True if command was handled."""
        text_lower = text.lower().strip()

        is_awaiting = self._ai.is_awaiting_question()
        has_wake_word = any(wake in text_lower for wake in WAKE_WORDS)
        has_leave_keyword = any(kw in text_lower for kw in LEAVE_KEYWORDS)

        if has_leave_keyword and (has_wake_word or is_awaiting):
            logger.info(f"Leave command from {speaker}")
            self._ai.clear_awaiting()
            await self._handle_leave_command(speaker)
            return True

        return False

    async def _handle_leave_command(self, speaker: str) -> None:
        """Handle request to leave the meeting."""
        from server.recall import get_recall_client
        from server.state import active_bots

        goodbye_text = f"Goodbye everyone! {speaker} asked me to leave. Feel free to invite me back anytime."

        await self._send_message(WSMessageType.TRANSCRIPT, {
            "speaker": "assistant",
            "text": goodbye_text,
            "is_final": True,
        })

        try:
            audio = await self._ai._generate_tts(goodbye_text)
            if audio:
                await self._send_audio(audio)
                await asyncio.sleep(3)
        except Exception as e:
            logger.error(f"TTS error: {e}")

        # Get bot_id - try state first, then fallback to active_bots lookup
        bot_id = self._state.bot_id
        if not bot_id:
            bot_id = active_bots.get(self._state.project_id)
            if bot_id:
                logger.info(f"bot_id not in state, found in active_bots: {bot_id}")

        if bot_id:
            try:
                client = get_recall_client()
                logger.info(f"Removing bot {bot_id} from meeting")
                await client.remove_bot(bot_id)
            except Exception as e:
                logger.error(f"Failed to remove bot {bot_id}: {e}")
        else:
            logger.error(f"Cannot leave - no bot_id for project {self._state.project_id}")

    async def _delayed_response_check(self) -> None:
        """Wait for silence before responding."""
        await asyncio.sleep(RESPONSE_DELAY_SEC + 0.1)

        time_since_last = time.time() - self._state.last_utterance_time

        if time_since_last >= (RESPONSE_DELAY_SEC - 0.1) and self._state.pending_response:
            self._state.pending_response = False
            await self._generate_and_send_response()

    async def _generate_and_send_response(self) -> None:
        """Query RAG and generate AI response."""
        if self._state.is_processing:
            return

        self._state.is_processing = True

        try:
            query = " ".join(list(self._state.utterances)[-3:])

            await self._send_thinking("processing", "Processing your question...", {
                "query": query[:100] + ("..." if len(query) > 100 else ""),
            })

            context, rag_results = await self._query_rag()

            if self._rag:
                if rag_results:
                    await self._send_thinking("context", f"Found {len(rag_results)} relevant memories", {
                        "query": query,
                        "results": [
                            {
                                "text": r.text,
                                "meeting": r.meeting_title,
                                "date": r.meeting_date.strftime("%b %d, %Y"),
                                "similarity": round(r.similarity, 2),
                            }
                            for r in rag_results
                        ]
                    })
                else:
                    await self._send_thinking("context", "No matching memories found", {
                        "query": query,
                        "results": [],
                    })
            else:
                await self._send_thinking("context", "Memory disabled for this meeting", {})

            await self._send_thinking("generating", "Generating response...", {})

            response = await self._ai.generate_response(include_audio=True)

            await self._send_thinking("complete", "Response ready", {})

            await self._send_message(WSMessageType.TRANSCRIPT, {
                "speaker": "assistant",
                "text": response.text,
                "is_final": True,
            })

            if response.audio:
                await self._send_audio(response.audio)

        except Exception as e:
            logger.exception(f"Response generation error: {e}")
            await self._send_error(f"Error: {str(e)}")
        finally:
            self._state.is_processing = False

    async def _send_greeting(self) -> None:
        """Generate and send initial greeting."""
        has_items = bool(self._rag and self._rag.get_action_items_context())
        response = await self._ai.generate_greeting(has_action_items=has_items)

        await self._send_message(WSMessageType.TRANSCRIPT, {
            "speaker": "assistant",
            "text": response.text,
            "is_final": True,
        })

        if response.audio:
            await self._send_audio(response.audio)

    async def _query_rag(self) -> tuple[str | None, list]:
        """Query RAG and update AI context."""
        if not self._rag:
            return None, []

        recent = list(self._state.utterances)[-5:]
        query = " ".join(recent)

        # Expand short follow-up questions with conversation context
        if recent and len(recent[-1].split()) < 8:
            conv_context = self._ai.get_recent_context()
            if conv_context:
                query = f"{conv_context} {query}"

        if not query.strip():
            return None, []

        results = await self._rag.query(query, auto_sync=False)

        if results:
            context = self._rag.format_context(results)
            self._ai.set_context(context)
            return context, results

        return None, []

    async def _receive_loop(self) -> None:
        """Process incoming WebSocket messages."""
        while True:
            try:
                msg = await self._ws.receive()

                if msg["type"] == "websocket.disconnect":
                    break

                if "text" in msg:
                    await self._handle_json(json.loads(msg["text"]))

            except WebSocketDisconnect:
                break

    async def _handle_json(self, data: dict) -> None:
        """Route incoming JSON messages."""
        msg_type = data.get("type")

        if msg_type == "transcript":
            speaker = data.get("speaker", "Unknown")
            text = data.get("text", "")
            is_final = data.get("is_final", False)
            if text:
                await self.receive_transcript(speaker, text, is_final)

        elif msg_type == "query" and self._rag:
            query = data.get("query", "")
            if query:
                results = await self._rag.query(query, auto_sync=False)
                context = self._rag.format_context(results)
                await self._send_message(WSMessageType.CONTEXT, {"context": context})

        elif msg_type == "set_bot_id":
            bot_id = data.get("bot_id")
            if bot_id:
                self._state.bot_id = bot_id

    async def _send_message(self, msg_type: WSMessageType, data: dict) -> None:
        """Send JSON message to client."""
        async with self._lock:
            try:
                await self._ws.send_json({"type": msg_type.value, "data": data})
            except Exception:
                pass

    async def _send_audio(self, audio_data: bytes) -> None:
        """Send audio for playback."""
        async with self._lock:
            try:
                await self._ws.send_json({
                    "type": "audio",
                    "data": {
                        "audio": base64.b64encode(audio_data).decode("utf-8"),
                        "format": "mp3",
                    }
                })
            except Exception:
                pass

    async def _send_thinking(self, step: str, message: str, data: dict = None) -> None:
        """Send thinking/visualization event to client."""
        payload = {"step": step, "message": message}
        if data:
            payload["data"] = data
        await self._send_message(WSMessageType.THINKING, payload)

    async def _send_status(self, status: str, message: str) -> None:
        """Send status update."""
        await self._send_message(WSMessageType.STATUS, {"status": status, "message": message})

    async def _send_error(self, error: str) -> None:
        """Send error message."""
        await self._send_message(WSMessageType.ERROR, {"error": error})
