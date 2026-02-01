"""Recall.ai webhook handlers."""
import logging

from fastapi import APIRouter

from server.constants import CHAT_REMOVE_COMMANDS
from server.rag.engine import get_rag_engine
from server.recall import get_recall_client
from server.state import active_handlers, project_handlers

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/webhooks/recall", tags=["webhooks"])


@router.post("/")
async def recall_webhook(payload: dict):
    """Handle Recall.ai event webhooks (bot.status_change, transcript.done)."""
    try:
        event = payload.get("event")
        data = payload.get("data", {})
        bot_id = data.get("bot_id")
        metadata = data.get("metadata", {}) or {}
        recurring_meeting_id = metadata.get("recurring_meeting_id")

        if event in ("bot.status_change", "transcript.done"):
            status = data.get("status", "")
            if event == "transcript.done" or status == "done":
                if recurring_meeting_id:
                    engine = get_rag_engine(recurring_meeting_id)
                    if engine:
                        result = await engine.sync_index()
                        return {"status": "indexed", **result}
                return {"status": "isolated"}

        return {"status": "acknowledged"}

    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return {"status": "error", "message": str(e)}


@router.post("/transcript")
async def recall_transcript_webhook(payload: dict):
    """Handle real-time transcript data from Recall.ai."""
    try:
        data = payload.get("data", {})
        bot_id = data.get("bot_id")
        metadata = data.get("metadata", {}) or {}
        project_id = metadata.get("project_id")

        # Try bot_id first, fallback to project_id
        handler = active_handlers.get(bot_id)
        if not handler and project_id:
            handler = project_handlers.get(project_id)
        if not handler:
            return {"status": "no_handler"}

        transcript = data.get("transcript", {})
        words = transcript.get("words", [])
        if not words:
            return {"status": "no_words"}

        text = " ".join(w.get("text", "") for w in words)
        speaker = transcript.get("speaker", "Unknown")

        await handler.receive_transcript(speaker=speaker, text=text, is_final=True)
        return {"status": "forwarded"}

    except Exception as e:
        logger.error(f"Transcript webhook error: {e}")
        return {"status": "error"}


@router.post("/chat")
async def recall_chat_webhook(payload: dict):
    """Handle chat messages - responds to 'remove' command."""
    try:
        event = payload.get("event")
        data = payload.get("data", {})
        bot_id = data.get("bot_id")

        if event != "participant_events.chat_message":
            return {"status": "ignored"}

        chat_data = data.get("data", {})
        message = chat_data.get("message", "").strip().lower()
        participant = data.get("participant", {})
        sender_name = participant.get("name", "Unknown")

        if message in CHAT_REMOVE_COMMANDS:
            logger.info(f"Remove command from {sender_name}")
            client = get_recall_client()

            try:
                await client.send_chat_message(
                    bot_id=bot_id,
                    message=f"Goodbye! Leaving as requested by {sender_name}.",
                )
            except Exception:
                pass

            await client.remove_bot(bot_id)
            return {"status": "removed"}

        return {"status": "acknowledged"}

    except Exception as e:
        logger.error(f"Chat webhook error: {e}")
        return {"status": "error"}
