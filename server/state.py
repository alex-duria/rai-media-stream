"""
In-memory state for active sessions.

Note: This is fine for a single-server demo. In production, use Redis or similar
for shared state across multiple server instances.
"""
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from server.websocket_handler import OutputMediaHandler

# Maps project_id -> bot_id for the currently active bot
active_bots: dict[str, str] = {}

# Maps bot_id -> handler for forwarding transcripts from webhooks
active_handlers: dict[str, "OutputMediaHandler"] = {}

# Maps project_id -> handler (for when bot_id isn't known yet due to race condition)
project_handlers: dict[str, "OutputMediaHandler"] = {}
