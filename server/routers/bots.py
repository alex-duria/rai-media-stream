"""Bot management endpoints."""
import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from server.config import get_settings
from server.constants import DEFAULT_JOIN_MESSAGE
from server.models import BotCreateRequest, BotCreateResponse
from server.recall import get_recall_client
from server.state import active_bots, active_handlers, project_handlers

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/bot", tags=["bots"])


@router.post("", response_model=BotCreateResponse)
async def create_bot(request: BotCreateRequest):
    """Create a Recall bot and dispatch it to a meeting."""
    try:
        settings = get_settings()
        client = get_recall_client()

        server_ws = settings.server_url.replace("http://", "").replace("https://", "")
        output_url = f"{settings.client_url}?project_id={request.project_id}&ws_host={server_ws}"

        if request.recurring_meeting_id:
            output_url += f"&recurring_meeting_id={request.recurring_meeting_id}"

        transcript_webhook_url = f"{settings.server_url}/webhooks/recall/transcript"

        bot = await client.create_bot(
            meeting_url=request.meeting_url,
            project_id=request.project_id,
            bot_name=request.bot_name,
            recurring_meeting_id=request.recurring_meeting_id,
            output_media_url=output_url,
            realtime_transcript_url=transcript_webhook_url,
            chat_on_join=DEFAULT_JOIN_MESSAGE,
        )

        active_bots[request.project_id] = bot.id

        # If handler already connected (race condition), update it with bot_id
        handler = project_handlers.get(request.project_id)
        if handler:
            handler._state.bot_id = bot.id
            active_handlers[bot.id] = handler

        return BotCreateResponse(
            bot_id=bot.id,
            meeting_url=request.meeting_url,
            project_id=request.project_id,
            recurring_meeting_id=request.recurring_meeting_id,
            status=bot.status,
        )
    except Exception as e:
        logger.error(f"Bot creation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{bot_id}")
async def get_bot(bot_id: str):
    """Get bot status."""
    try:
        client = get_recall_client()
        bot = await client.get_bot(bot_id)
        return {
            "id": bot.id,
            "status": bot.status,
            "project_id": bot.project_id,
            "recurring_meeting_id": bot.recurring_meeting_id,
            "meeting_url": bot.meeting_url,
            "has_transcript": bot.transcript_url is not None,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class ChatMessageRequest(BaseModel):
    message: str
    send_to: str = "everyone"


@router.post("/{bot_id}/chat")
async def send_chat_message(bot_id: str, request: ChatMessageRequest):
    """Send a chat message from the bot."""
    try:
        client = get_recall_client()
        result = await client.send_chat_message(
            bot_id=bot_id,
            message=request.message,
            send_to=request.send_to,
        )
        return {"status": "sent", "result": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{bot_id}/leave")
async def remove_bot(bot_id: str):
    """Remove the bot from the meeting."""
    try:
        client = get_recall_client()
        await client.remove_bot(bot_id)
        return {"status": "removed", "bot_id": bot_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{bot_id}/speaker-timeline")
async def get_speaker_timeline(bot_id: str):
    """Get speaker timeline for a completed meeting."""
    try:
        client = get_recall_client()
        timeline = await client.get_speaker_timeline(bot_id)
        if timeline is None:
            raise HTTPException(status_code=404, detail="Timeline not available")
        return {"bot_id": bot_id, "events": timeline}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{bot_id}/chat-history")
async def get_chat_history(bot_id: str):
    """Get chat messages from a completed meeting."""
    try:
        client = get_recall_client()
        messages = await client.get_chat_messages(bot_id)
        return {"bot_id": bot_id, "messages": messages}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
