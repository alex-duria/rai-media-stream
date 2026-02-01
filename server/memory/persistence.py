"""Simple JSON persistence for local cache data."""
from __future__ import annotations

import json
from pathlib import Path
from functools import lru_cache

from server.config import get_settings


@lru_cache(maxsize=32)
def get_project_dir(project_id: str) -> Path:
    """Get or create directory for a project's local cache."""
    settings = get_settings()
    project_dir = Path(settings.data_dir) / "projects" / project_id
    project_dir.mkdir(parents=True, exist_ok=True)
    return project_dir


def get_action_items_path(project_id: str) -> Path:
    """Get path to action_items.json for a project."""
    return get_project_dir(project_id) / "action_items.json"


def load_json(file_path: Path, default=None):
    """Load JSON from file."""
    if not file_path.exists():
        return default if default is not None else {}
    with open(file_path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(file_path: Path, data) -> None:
    """Save data to JSON file."""
    file_path.parent.mkdir(parents=True, exist_ok=True)
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=str)
