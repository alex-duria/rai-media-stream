"""Project-scoped endpoints."""
import logging

from fastapi import APIRouter, HTTPException, Query

from server.models import ActionItemStatus
from server.recall import get_recall_client
from server.rag.engine import get_rag_engine
from server.memory.action_items import get_action_items, complete_action_item

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/projects/{project_id}", tags=["projects"])


@router.get("/bots")
async def list_project_bots(project_id: str):
    """List all bots for this project."""
    try:
        client = get_recall_client()
        bots = await client.list_project_bots(project_id)
        return {
            "project_id": project_id,
            "count": len(bots),
            "bots": [
                {
                    "id": b.id,
                    "status": b.status,
                    "meeting_url": b.meeting_url,
                    "recurring_meeting_id": b.recurring_meeting_id,
                    "created_at": b.created_at.isoformat() if b.created_at else None,
                    "has_transcript": b.transcript_url is not None,
                }
                for b in bots
            ],
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/context")
async def query_context(
    project_id: str,
    query: str = Query(...),
    recurring_meeting_id: str = Query(...),
    sync: bool = Query(True),
):
    """Query RAG context from a recurring meeting series."""
    try:
        engine = get_rag_engine(recurring_meeting_id)
        if not engine:
            return {
                "query": query,
                "recurring_meeting_id": recurring_meeting_id,
                "count": 0,
                "results": [],
                "context": "",
            }

        results = await engine.query(query, auto_sync=sync)
        return {
            "query": query,
            "recurring_meeting_id": recurring_meeting_id,
            "count": len(results),
            "results": [
                {
                    "text": r.text,
                    "meeting_title": r.meeting_title,
                    "meeting_date": r.meeting_date.isoformat(),
                    "similarity": r.similarity,
                }
                for r in results
            ],
            "context": engine.format_context(results),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/sync")
async def sync_project(
    project_id: str,
    recurring_meeting_id: str = Query(...),
):
    """Sync vector index for a recurring meeting series."""
    try:
        engine = get_rag_engine(recurring_meeting_id)
        if not engine:
            return {"indexed": 0, "total_bots": 0}

        result = await engine.sync_index()
        return {"project_id": project_id, "recurring_meeting_id": recurring_meeting_id, **result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/action-items")
async def list_action_items(project_id: str, status: str | None = None):
    """List action items from meeting transcripts."""
    try:
        status_filter = None
        if status:
            try:
                status_filter = ActionItemStatus(status)
            except ValueError:
                raise HTTPException(status_code=400, detail=f"Invalid status: {status}")

        items = get_action_items(project_id, status_filter)
        return {
            "project_id": project_id,
            "count": len(items),
            "items": [i.model_dump(mode="json") for i in items],
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/action-items/{item_id}/complete")
async def complete_item(project_id: str, item_id: str):
    """Mark an action item as completed."""
    item = complete_action_item(project_id, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Action item not found")
    return item.model_dump(mode="json")
