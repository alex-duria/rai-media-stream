"""API routers."""
from server.routers.bots import router as bots_router
from server.routers.projects import router as projects_router
from server.routers.webhooks import router as webhooks_router

__all__ = ["bots_router", "projects_router", "webhooks_router"]
