"""
Action Item Detection and Storage.

Detects action items from meeting transcripts using pattern matching.
Phrases like "remind me to...", "circle back on...", "follow up with..."
are captured and stored for proactive surfacing in future meetings.
"""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Iterator
from functools import lru_cache

from server.models import ActionItem, ActionItemStatus
from server.memory.persistence import get_action_items_path, load_json, save_json


@dataclass(frozen=True, slots=True)
class ActionPattern:
    """Compiled regex pattern for action item detection."""
    regex: re.Pattern
    name: str


@lru_cache(maxsize=1)
def _get_compiled_patterns() -> tuple[ActionPattern, ...]:
    """Get pre-compiled patterns (cached for performance)."""
    patterns = [
        (r"remind me (?:to|about) (.+?)(?:\.|$)", "remind me"),
        (r"circle back (?:on|to) (.+?)(?:\.|$)", "circle back"),
        (r"follow up (?:on|with) (.+?)(?:\.|$)", "follow up"),
        (r"action item[:\s]+(.+?)(?:\.|$)", "action item"),
        (r"don'?t forget (?:to )?(.+?)(?:\.|$)", "don't forget"),
        (r"let'?s revisit (.+?)(?:\.|$)", "revisit"),
        (r"todo[:\s]+(.+?)(?:\.|$)", "todo"),
    ]
    return tuple(
        ActionPattern(re.compile(p, re.IGNORECASE), name)
        for p, name in patterns
    )


# Patterns for extracting assignee from context
_ASSIGNEE_PATTERN = re.compile(r"([A-Z][a-z]+)[,:]?\s*(?:can you|please|could you)")
_FOR_PATTERN = re.compile(r"(?:for|with)\s+([A-Z][a-z]+)")


def detect_action_items(
    text: str,
    project_id: str,
    meeting_id: str,
    speaker: Optional[str] = None
) -> Iterator[ActionItem]:
    """
    Detect action items in text using pattern matching.

    Yields ActionItem objects for each detected phrase.
    Deduplicates by normalized text within the same call.
    """
    patterns = _get_compiled_patterns()
    seen_texts: set[str] = set()

    for pattern in patterns:
        for match in pattern.regex.finditer(text):
            action_text = match.group(1).strip()

            # Skip short or duplicate matches
            if len(action_text) < 5 or action_text.lower() in seen_texts:
                continue

            seen_texts.add(action_text.lower())

            yield ActionItem(
                item_id=str(uuid.uuid4()),
                project_id=project_id,
                meeting_id=meeting_id,
                text=action_text,
                pattern_matched=pattern.name,
                assignee=_extract_assignee(text, match.start()) or speaker,
                status=ActionItemStatus.PENDING,
                created_at=datetime.utcnow(),
            )


def _extract_assignee(text: str, position: int) -> Optional[str]:
    """Try to extract assignee name from surrounding context."""
    start = max(0, position - 50)
    end = min(len(text), position + 50)
    context = text[start:end]

    match = _ASSIGNEE_PATTERN.search(context) or _FOR_PATTERN.search(context)
    return match.group(1) if match else None


class ActionItemStore:
    """
    In-memory store with JSON persistence for action items.

    Handles deduplication by text to avoid storing the same action item
    multiple times across transcript re-processing.
    """

    __slots__ = ("project_id", "_items", "_text_index", "_dirty")

    def __init__(self, project_id: str):
        self.project_id = project_id
        self._items: dict[str, ActionItem] = {}
        self._text_index: set[str] = set()  # For deduplication
        self._dirty = False

    def load(self) -> None:
        """Load items from disk."""
        path = get_action_items_path(self.project_id)
        data = load_json(path, default=[])
        self._items = {
            item["item_id"]: ActionItem.model_validate(item)
            for item in data
        }
        self._text_index = {item.text.lower() for item in self._items.values()}
        self._dirty = False

    def save(self) -> None:
        """Save items to disk if modified."""
        if not self._dirty:
            return
        path = get_action_items_path(self.project_id)
        data = [item.model_dump(mode="json") for item in self._items.values()]
        save_json(path, data)
        self._dirty = False

    def add(self, item: ActionItem) -> bool:
        """Add item if not duplicate. Returns True if added."""
        key = item.text.lower()
        if key in self._text_index:
            return False

        self._items[item.item_id] = item
        self._text_index.add(key)
        self._dirty = True
        return True

    def add_many(self, items: Iterator[ActionItem]) -> int:
        """Add multiple items, returns count added."""
        return sum(1 for item in items if self.add(item))

    def get(self, item_id: str) -> Optional[ActionItem]:
        """Get item by ID."""
        return self._items.get(item_id)

    def get_by_status(self, status: ActionItemStatus) -> list[ActionItem]:
        """Get items filtered by status."""
        return [item for item in self._items.values() if item.status == status]

    def get_pending(self) -> list[ActionItem]:
        """Get pending items for surfacing."""
        return self.get_by_status(ActionItemStatus.PENDING)

    def mark_surfaced(self, item_ids: list[str]) -> None:
        """Mark items as surfaced (mentioned in a meeting)."""
        now = datetime.utcnow()
        for item_id in item_ids:
            if item := self._items.get(item_id):
                self._items[item_id] = ActionItem(
                    **{**item.model_dump(), "status": ActionItemStatus.SURFACED, "surfaced_at": now}
                )
                self._dirty = True

    def complete(self, item_id: str) -> Optional[ActionItem]:
        """Mark item as completed."""
        if item := self._items.get(item_id):
            updated = ActionItem(
                **{**item.model_dump(), "status": ActionItemStatus.COMPLETED, "completed_at": datetime.utcnow()}
            )
            self._items[item_id] = updated
            self._dirty = True
            return updated
        return None

    def __len__(self) -> int:
        return len(self._items)

    def __iter__(self) -> Iterator[ActionItem]:
        return iter(self._items.values())


# --- Store Registry ---

_stores: dict[str, ActionItemStore] = {}


def get_action_item_store(project_id: str) -> ActionItemStore:
    """Get or create action item store for project."""
    if project_id not in _stores:
        store = ActionItemStore(project_id)
        store.load()
        _stores[project_id] = store
    return _stores[project_id]


# --- Convenience Functions ---

def get_action_items(project_id: str, status: Optional[ActionItemStatus] = None) -> list[ActionItem]:
    """Get action items, optionally filtered by status."""
    store = get_action_item_store(project_id)
    if status:
        return store.get_by_status(status)
    return list(store)


def get_pending_action_items(project_id: str) -> list[ActionItem]:
    """Get pending action items for a project."""
    return get_action_item_store(project_id).get_pending()


def complete_action_item(project_id: str, item_id: str) -> Optional[ActionItem]:
    """Mark an action item as completed."""
    store = get_action_item_store(project_id)
    result = store.complete(item_id)
    store.save()
    return result


def format_action_items_for_prompt(items: list[ActionItem]) -> str:
    """Format action items for injection into LLM prompt."""
    if not items:
        return ""

    lines = ["Pending action items from previous meetings:"]
    lines.extend(
        f"{i}. {item.text}" + (f" (assigned to {item.assignee})" if item.assignee else "")
        for i, item in enumerate(items, 1)
    )
    return "\n".join(lines)
