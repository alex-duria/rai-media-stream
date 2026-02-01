"""Recall - Meeting Memory Bot"""
import logging
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from server.websocket_handler import OutputMediaHandler
from server.routers import bots_router, projects_router, webhooks_router
from server.state import active_bots, active_handlers, project_handlers

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Recall",
    description="Meeting memory bot with RAG",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(bots_router)
app.include_router(projects_router)
app.include_router(webhooks_router)


@app.get("/health", tags=["health"])
async def health():
    """Health check endpoint."""
    return {"status": "healthy", "timestamp": datetime.utcnow().isoformat()}


@app.websocket("/ws/{project_id}")
async def websocket_endpoint(
    websocket: WebSocket,
    project_id: str,
    bot_id: str = None,
    recurring_meeting_id: str = None,
):
    """Output media WebSocket endpoint."""
    if not bot_id:
        bot_id = active_bots.get(project_id)

    handler = OutputMediaHandler(
        websocket,
        project_id,
        recurring_meeting_id=recurring_meeting_id,
        bot_id=bot_id,
    )

    # Always register by project_id (for bot creation to find us)
    project_handlers[project_id] = handler

    # Also register by bot_id if known
    if bot_id:
        active_handlers[bot_id] = handler

    try:
        await handler.handle()
    finally:
        if project_id in project_handlers:
            del project_handlers[project_id]
        # Check handler's state for bot_id (may have been set after connection)
        final_bot_id = handler._state.bot_id
        if final_bot_id and final_bot_id in active_handlers:
            del active_handlers[final_bot_id]


# Static files (client)
CLIENT_DIST = Path(__file__).parent.parent / "client" / "dist"

if CLIENT_DIST.exists():
    app.mount("/assets", StaticFiles(directory=CLIENT_DIST / "assets"), name="assets")

    @app.get("/", include_in_schema=False)
    async def serve_client():
        return FileResponse(CLIENT_DIST / "index.html")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_client_fallback(full_path: str):
        if full_path.startswith(("api/", "ws/", "webhooks/", "health")):
            return FileResponse(CLIENT_DIST / "index.html")
        file_path = CLIENT_DIST / full_path
        if file_path.exists() and file_path.is_file():
            return FileResponse(file_path)
        return FileResponse(CLIENT_DIST / "index.html")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
