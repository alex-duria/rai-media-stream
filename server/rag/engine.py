"""RAG Engine - retrieves relevant context from past meeting transcripts."""
from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import numpy as np
from numpy.typing import NDArray
from openai import OpenAI

from server.config import get_settings
from server.recall.client import get_recall_client, RecallClient, BotInfo
from server.memory.action_items import (
    detect_action_items,
    get_action_item_store,
    format_action_items_for_prompt,
)

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class Chunk:
    """Embedded text chunk from a meeting transcript."""
    bot_id: str
    text: str
    embedding: NDArray[np.float32]
    meeting_title: str
    meeting_date: datetime
    recurring_meeting_id: str | None = None


@dataclass
class SearchResult:
    """RAG search result with source metadata."""
    text: str
    bot_id: str
    meeting_title: str
    meeting_date: datetime
    similarity: float
    recurring_meeting_id: str | None = None


@dataclass
class VectorCache:
    """In-memory vector cache with disk persistence."""
    project_id: str
    chunks: list[Chunk] = field(default_factory=list)
    indexed_bots: set[str] = field(default_factory=set)
    _matrix: NDArray[np.float32] | None = field(default=None, repr=False)

    def add_chunks(self, new_chunks: list[Chunk]) -> None:
        self.chunks.extend(new_chunks)
        self._matrix = None

    def get_matrix(self) -> NDArray[np.float32] | None:
        if not self.chunks:
            return None
        if self._matrix is None:
            self._matrix = np.vstack([c.embedding for c in self.chunks])
        return self._matrix

    def search(
        self,
        query_embedding: NDArray[np.float32],
        top_k: int = 5,
        threshold: float = 0.65,
    ) -> list[SearchResult]:
        """Cosine similarity search."""
        matrix = self.get_matrix()
        if matrix is None:
            return []

        query_norm = np.linalg.norm(query_embedding)
        chunk_norms = np.linalg.norm(matrix, axis=1)
        similarities = (matrix @ query_embedding) / (chunk_norms * query_norm + 1e-10)

        indices = np.where(similarities >= threshold)[0]
        if len(indices) == 0:
            return []

        top_indices = indices[np.argsort(similarities[indices])[-top_k:][::-1]]

        return [
            SearchResult(
                text=self.chunks[i].text,
                bot_id=self.chunks[i].bot_id,
                meeting_title=self.chunks[i].meeting_title,
                meeting_date=self.chunks[i].meeting_date,
                similarity=float(similarities[i]),
                recurring_meeting_id=self.chunks[i].recurring_meeting_id,
            )
            for i in top_indices
        ]

    def save(self, path: Path) -> None:
        data = {
            "indexed_bots": list(self.indexed_bots),
            "chunks": [
                {
                    "bot_id": c.bot_id,
                    "text": c.text,
                    "embedding": c.embedding.tolist(),
                    "meeting_title": c.meeting_title,
                    "meeting_date": c.meeting_date.isoformat(),
                    "recurring_meeting_id": c.recurring_meeting_id,
                }
                for c in self.chunks
            ],
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            json.dump(data, f)

    @classmethod
    def load(cls, project_id: str, path: Path) -> "VectorCache":
        cache = cls(project_id=project_id)
        if not path.exists():
            return cache

        try:
            with open(path) as f:
                data = json.load(f)

            cache.indexed_bots = set(data.get("indexed_bots", []))
            cache.chunks = [
                Chunk(
                    bot_id=c["bot_id"],
                    text=c["text"],
                    embedding=np.array(c["embedding"], dtype=np.float32),
                    meeting_title=c["meeting_title"],
                    meeting_date=datetime.fromisoformat(c["meeting_date"]),
                    recurring_meeting_id=c.get("recurring_meeting_id"),
                )
                for c in data.get("chunks", [])
            ]
        except Exception as e:
            logger.warning(f"Failed to load vector cache: {e}")

        return cache


class RAGEngine:
    """RAG engine for a recurring meeting series."""

    __slots__ = ("recurring_meeting_id", "_settings", "_openai", "_cache", "_recall", "_lock")

    def __init__(self, recurring_meeting_id: str):
        self.recurring_meeting_id = recurring_meeting_id
        self._settings = get_settings()
        self._openai: OpenAI | None = None
        self._recall: RecallClient | None = None
        self._cache: VectorCache | None = None
        self._lock = asyncio.Lock()

    @property
    def openai(self) -> OpenAI:
        if self._openai is None:
            self._openai = OpenAI(api_key=self._settings.openai_api_key)
        return self._openai

    @property
    def recall(self) -> RecallClient:
        if self._recall is None:
            self._recall = get_recall_client()
        return self._recall

    @property
    def cache(self) -> VectorCache:
        if self._cache is None:
            self._cache = VectorCache.load(self.recurring_meeting_id, self._cache_path())
        return self._cache

    def _cache_path(self) -> Path:
        return Path(self._settings.data_dir) / "meetings" / self.recurring_meeting_id / "vectors.json"

    def _get_embedding(self, text: str) -> NDArray[np.float32]:
        response = self.openai.embeddings.create(
            model=self._settings.openai_embedding_model,
            input=text,
        )
        return np.array(response.data[0].embedding, dtype=np.float32)

    def _get_embeddings_batch(self, texts: list[str]) -> list[NDArray[np.float32]]:
        if not texts:
            return []
        response = self.openai.embeddings.create(
            model=self._settings.openai_embedding_model,
            input=texts,
        )
        return [
            np.array(item.embedding, dtype=np.float32)
            for item in sorted(response.data, key=lambda x: x.index)
        ]

    def _chunk_text(self, text: str, chunk_size: int = 500) -> list[str]:
        """Split text into chunks at sentence boundaries."""
        sentences = re.split(r"(?<=[.!?])\s+", text.replace("\n", " ").strip())
        sentences = [s.strip() for s in sentences if s.strip()]

        chunks = []
        current = []
        current_len = 0

        for sentence in sentences:
            if current_len + len(sentence) > chunk_size and current:
                chunks.append(" ".join(current))
                current = current[-1:] if current else []
                current_len = sum(len(s) for s in current)

            current.append(sentence)
            current_len += len(sentence)

        if current:
            chunks.append(" ".join(current))

        return chunks

    async def sync_index(self, force: bool = False) -> dict:
        """Sync vector index with Recall.ai transcripts."""
        async with self._lock:
            bots = await self.recall.list_recurring_meeting_bots(self.recurring_meeting_id)

            to_index = [
                b for b in bots
                if b.status == "done"
                and b.transcript_url
                and (force or b.id not in self.cache.indexed_bots)
            ]

            if not to_index:
                return {"indexed": 0, "total_bots": len(bots)}

            indexed = 0
            for bot in to_index:
                try:
                    await self._index_bot(bot)
                    indexed += 1
                except Exception as e:
                    logger.error(f"Failed to index bot {bot.id}: {e}")

            self.cache.save(self._cache_path())
            return {"indexed": indexed, "total_bots": len(bots)}

    async def _index_bot(self, bot: BotInfo) -> None:
        """Index a single bot's transcript."""
        utterances = await self.recall.fetch_transcript(bot.transcript_url)
        if not utterances:
            return

        full_text = "\n".join(
            f"{u.speaker_name or 'Speaker'}: {u.text}" for u in utterances
        )

        chunks = self._chunk_text(full_text)
        if not chunks:
            return

        embeddings = self._get_embeddings_batch(chunks)
        meeting_title = self._extract_meeting_title(bot)
        meeting_date = bot.created_at or datetime.utcnow()

        new_chunks = [
            Chunk(
                bot_id=bot.id,
                text=text,
                embedding=emb,
                meeting_title=meeting_title,
                meeting_date=meeting_date,
                recurring_meeting_id=self.recurring_meeting_id,
            )
            for text, emb in zip(chunks, embeddings)
        ]

        self.cache.add_chunks(new_chunks)
        self.cache.indexed_bots.add(bot.id)

        # Extract action items
        action_store = get_action_item_store(self.recurring_meeting_id)
        items = detect_action_items(full_text, self.recurring_meeting_id, bot.id)
        action_store.add_many(items)
        action_store.save()

    def _extract_meeting_title(self, bot: BotInfo) -> str:
        date_str = bot.created_at.strftime('%b %d') if bot.created_at else 'Unknown'

        if "zoom" in bot.meeting_url.lower():
            return f"Zoom Meeting ({date_str})"
        elif "meet.google" in bot.meeting_url.lower():
            return f"Google Meet ({date_str})"
        elif "teams" in bot.meeting_url.lower():
            return f"Teams Meeting ({date_str})"
        return bot.bot_name or "Meeting"

    async def query(
        self,
        query: str,
        top_k: int = 5,
        threshold: float = None,
        auto_sync: bool = True,
    ) -> list[SearchResult]:
        """Query the RAG system for relevant context."""
        if auto_sync:
            await self.sync_index()

        threshold = threshold or self._settings.rag_similarity_threshold
        query_embedding = self._get_embedding(query)

        return self.cache.search(query_embedding, top_k=top_k, threshold=threshold)

    def format_context(self, results: list[SearchResult]) -> str:
        """Format search results as context for LLM."""
        if not results:
            return ""

        lines = ["Relevant context from previous meetings:\n"]
        for r in results:
            date_str = r.meeting_date.strftime("%B %d, %Y")
            lines.append(f"From '{r.meeting_title}' on {date_str}:")
            lines.append(f'"{r.text}"\n')

        return "\n".join(lines)

    def get_action_items_context(self) -> str:
        """Get pending action items for prompt injection."""
        store = get_action_item_store(self.recurring_meeting_id)
        pending = store.get_pending()
        return format_action_items_for_prompt(pending)


_engines: dict[str, RAGEngine] = {}


def get_rag_engine(recurring_meeting_id: str | None) -> RAGEngine | None:
    """Get or create RAG engine. Returns None if no recurring_meeting_id."""
    if not recurring_meeting_id:
        return None
    if recurring_meeting_id not in _engines:
        _engines[recurring_meeting_id] = RAGEngine(recurring_meeting_id)
    return _engines[recurring_meeting_id]
