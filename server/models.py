"""Pydantic models for the API."""
from datetime import datetime
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


# --- Action Item Models ---

class ActionItemStatus(str, Enum):
    """Status of an action item."""
    PENDING = "pending"
    SURFACED = "surfaced"
    COMPLETED = "completed"


class ActionItem(BaseModel):
    """Detected action item from transcript."""
    item_id: str
    project_id: str
    meeting_id: str  # bot_id from Recall.ai
    text: str
    pattern_matched: str
    assignee: Optional[str] = None
    status: ActionItemStatus = ActionItemStatus.PENDING
    created_at: datetime = Field(default_factory=datetime.utcnow)
    surfaced_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


# --- Bot Models ---

class BotCreateRequest(BaseModel):
    """Request to create a Recall bot."""
    meeting_url: str
    project_id: str
    bot_name: str = "Recall"
    recurring_meeting_id: Optional[str] = None


class BotCreateResponse(BaseModel):
    """Response from bot creation."""
    bot_id: str
    meeting_url: str
    project_id: str
    recurring_meeting_id: Optional[str] = None
    status: str


# --- WebSocket Models ---

class WSMessageType(str, Enum):
    """WebSocket message types."""
    AUDIO = "audio"
    TRANSCRIPT = "transcript"
    CONTEXT = "context"
    ACTION_ITEMS = "action_items"
    STATUS = "status"
    ERROR = "error"
    # Agent thinking/tool use events for visualization
    THINKING = "thinking"  # Shows what the agent is doing
