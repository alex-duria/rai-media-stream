"""Recall.ai API Client."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import AsyncIterator
from dataclasses import dataclass

import httpx

from server.config import get_settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class TranscriptUtterance:
    """A single speaker utterance from a transcript."""
    speaker_id: int
    speaker_name: str | None
    text: str
    start_time: float
    end_time: float | None


@dataclass(slots=True)
class BotInfo:
    """Bot information from Recall.ai."""
    id: str
    meeting_url: str
    bot_name: str
    status: str
    project_id: str | None
    recurring_meeting_id: str | None
    created_at: datetime | None
    recording_id: str | None
    transcript_url: str | None

    @classmethod
    def from_api(cls, data: dict) -> "BotInfo":
        metadata = data.get("metadata", {}) or {}
        recording = data.get("recording") or {}
        media_shortcuts = recording.get("media_shortcuts") or {}
        transcript_info = media_shortcuts.get("transcript") or {}

        created_at = None
        if created_str := data.get("created_at"):
            try:
                created_at = datetime.fromisoformat(created_str.replace("Z", "+00:00"))
            except (ValueError, TypeError):
                pass

        meeting_url = data.get("meeting_url", "")
        if isinstance(meeting_url, dict):
            meeting_url = meeting_url.get("url", "")

        return cls(
            id=data["id"],
            meeting_url=meeting_url,
            bot_name=data.get("bot_name", ""),
            status=data.get("status", "unknown"),
            project_id=metadata.get("project_id"),
            recurring_meeting_id=metadata.get("recurring_meeting_id"),
            created_at=created_at,
            recording_id=recording.get("id"),
            transcript_url=transcript_info.get("download_url"),
        )


class RecallClient:
    """Async client for Recall.ai API."""

    __slots__ = ("_settings", "_base_url")

    def __init__(self):
        self._settings = get_settings()
        self._base_url = f"https://{self._settings.recall_region}.recall.ai/api/v1"

    def _headers(self) -> dict:
        return {
            "Authorization": f"Token {self._settings.recall_api_key}",
            "Content-Type": "application/json",
        }

    async def create_bot(
        self,
        meeting_url: str,
        project_id: str,
        bot_name: str = "Recall",
        recurring_meeting_id: str | None = None,
        output_media_url: str | None = None,
        realtime_transcript_url: str | None = None,
        chat_on_join: str | None = None,
    ) -> BotInfo:
        """Create a bot and send it to join a meeting."""
        metadata = {"project_id": project_id}
        if recurring_meeting_id:
            metadata["recurring_meeting_id"] = recurring_meeting_id

        payload = {
            "meeting_url": meeting_url,
            "bot_name": bot_name,
            "metadata": metadata,
            "recording_config": {
                "transcript": {
                    "provider": {
                        "recallai_streaming": {
                            "mode": "prioritize_low_latency",
                            "language_code": "en",
                        }
                    },
                    "diarization": {
                        "use_separate_streams_when_available": True,
                    },
                },
            },
            "automatic_leave": {
                "waiting_room_timeout": 600,
                "noone_joined_timeout": 600,
                "everyone_left_timeout": 3,
                "silence_detection": {
                    "timeout": 3600,
                    "activate_after": 300,
                },
            },
        }

        if realtime_transcript_url:
            payload["recording_config"]["realtime_endpoints"] = [
                {
                    "type": "webhook",
                    "url": realtime_transcript_url,
                    "events": ["transcript.data", "speaker.update"],
                }
            ]

        if output_media_url:
            payload["output_media"] = {
                "camera": {"kind": "webpage", "config": {"url": output_media_url}}
            }

        if chat_on_join:
            payload["chat"] = {
                "on_bot_join": {"message": chat_on_join, "send_to": "everyone"}
            }

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{self._base_url}/bot/",
                headers=self._headers(),
                json=payload,
            )
            response.raise_for_status()
            return BotInfo.from_api(response.json())

    async def get_bot(self, bot_id: str) -> BotInfo:
        """Get current bot status."""
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                f"{self._base_url}/bot/{bot_id}/",
                headers=self._headers(),
            )
            response.raise_for_status()
            return BotInfo.from_api(response.json())

    async def list_bots(
        self,
        project_id: str | None = None,
        recurring_meeting_id: str | None = None,
        limit: int = 100,
        cursor: str | None = None,
    ) -> tuple[list[BotInfo], str | None]:
        """List bots with optional metadata filters."""
        params = {"limit": limit}
        if project_id:
            params["metadata__project_id"] = project_id
        if recurring_meeting_id:
            params["metadata__recurring_meeting_id"] = recurring_meeting_id
        if cursor:
            params["cursor"] = cursor

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                f"{self._base_url}/bot/",
                headers=self._headers(),
                params=params,
            )
            response.raise_for_status()
            data = response.json()

            bots = [BotInfo.from_api(b) for b in data.get("results", [])]
            return bots, data.get("next")

    async def iter_project_bots(self, project_id: str) -> AsyncIterator[BotInfo]:
        """Iterate all bots for a project."""
        cursor = None
        while True:
            bots, cursor = await self.list_bots(project_id=project_id, cursor=cursor)
            for bot in bots:
                yield bot
            if not cursor:
                break

    async def list_project_bots(self, project_id: str) -> list[BotInfo]:
        """Get all bots for a project."""
        return [bot async for bot in self.iter_project_bots(project_id)]

    async def iter_recurring_meeting_bots(self, recurring_meeting_id: str) -> AsyncIterator[BotInfo]:
        """Iterate all bots for a recurring meeting series."""
        cursor = None
        while True:
            bots, cursor = await self.list_bots(recurring_meeting_id=recurring_meeting_id, cursor=cursor)
            for bot in bots:
                yield bot
            if not cursor:
                break

    async def list_recurring_meeting_bots(self, recurring_meeting_id: str) -> list[BotInfo]:
        """Get all bots for a recurring meeting series."""
        return [bot async for bot in self.iter_recurring_meeting_bots(recurring_meeting_id)]

    async def remove_bot(self, bot_id: str) -> None:
        """Remove bot from meeting."""
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{self._base_url}/bot/{bot_id}/leave_call/",
                headers=self._headers(),
            )
            response.raise_for_status()

    async def send_chat_message(
        self,
        bot_id: str,
        message: str,
        send_to: str = "everyone",
    ) -> dict:
        """Send a chat message from the bot."""
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{self._base_url}/bot/{bot_id}/send_chat_message/",
                headers=self._headers(),
                json={"message": message, "to": send_to},
            )
            response.raise_for_status()
            return response.json()

    async def get_recording(self, recording_id: str) -> dict:
        """Get recording details."""
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                f"{self._base_url}/recording/{recording_id}/",
                headers=self._headers(),
            )
            response.raise_for_status()
            return response.json()

    async def get_speaker_timeline(self, bot_id: str) -> list[dict] | None:
        """Get speaker timeline for a completed meeting."""
        bot = await self.get_bot(bot_id)
        if not bot.recording_id:
            return None

        recording = await self.get_recording(bot.recording_id)
        media_shortcuts = recording.get("media_shortcuts", {})
        speaker_data = media_shortcuts.get("speaker_timeline", {})
        download_url = speaker_data.get("download_url")

        if not download_url:
            return None

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.get(download_url)
            response.raise_for_status()
            return response.json()

    async def get_participant_events(self, bot_id: str) -> list[dict] | None:
        """Get participant events including chat messages."""
        bot = await self.get_bot(bot_id)
        if not bot.recording_id:
            return None

        recording = await self.get_recording(bot.recording_id)
        media_shortcuts = recording.get("media_shortcuts", {})
        events_data = media_shortcuts.get("participant_events", {}).get("data", {})
        download_url = events_data.get("participant_events_download_url")

        if not download_url:
            return None

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.get(download_url)
            response.raise_for_status()
            return response.json()

    async def get_chat_messages(self, bot_id: str) -> list[dict]:
        """Extract chat messages from participant events."""
        events = await self.get_participant_events(bot_id)
        if not events:
            return []

        return [
            {
                "participant": e.get("participant", {}),
                "message": e.get("data", {}).get("message", ""),
                "timestamp": e.get("timestamp"),
            }
            for e in events
            if e.get("type") == "chat_message"
        ]

    async def fetch_transcript(self, transcript_url: str) -> list[TranscriptUtterance]:
        """Fetch and parse transcript from download URL."""
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.get(transcript_url)
            response.raise_for_status()
            data = response.json()

        utterances = []
        for item in data:
            speaker = item.get("participant", {}) or {}
            words = item.get("words", [])

            if not words:
                continue

            text = " ".join(w.get("text", "") for w in words).strip()
            if not text:
                continue

            start_time = words[0].get("start_timestamp", {}).get("relative", 0.0)
            end_time = words[-1].get("end_timestamp", {}).get("relative")

            utterances.append(TranscriptUtterance(
                speaker_id=speaker.get("id", 0),
                speaker_name=speaker.get("name"),
                text=text,
                start_time=start_time,
                end_time=end_time,
            ))

        return utterances

    async def get_bot_transcript(self, bot_id: str) -> list[TranscriptUtterance] | None:
        """Get transcript for a bot if available."""
        bot = await self.get_bot(bot_id)
        if not bot.transcript_url:
            return None
        return await self.fetch_transcript(bot.transcript_url)


_client: RecallClient | None = None


def get_recall_client() -> RecallClient:
    """Get singleton Recall client instance."""
    global _client
    if _client is None:
        _client = RecallClient()
    return _client
