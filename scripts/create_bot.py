#!/usr/bin/env python3
"""CLI script to create a Recall bot for a meeting."""
import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from server.recall import get_recall_client
from server.config import get_settings


async def create_bot(
    meeting_url: str,
    project_id: str,
    bot_name: str,
    recurring_meeting_id: str | None = None,
) -> None:
    """Create a Recall bot."""
    client = get_recall_client()
    settings = get_settings()

    output_url = f"{settings.client_url}?project_id={project_id}"
    if recurring_meeting_id:
        output_url += f"&recurring_meeting_id={recurring_meeting_id}"

    print(f"Creating bot for: {meeting_url}")
    print(f"Project ID: {project_id}")
    if recurring_meeting_id:
        print(f"Recurring Meeting ID: {recurring_meeting_id}")
        print(f"  (RAG will query only meetings with this ID)")
    else:
        print(f"Recurring Meeting ID: None")
        print(f"  (RAG disabled - meeting is isolated)")
    print(f"Output URL: {output_url}")
    print()

    bot = await client.create_bot(
        meeting_url=meeting_url,
        project_id=project_id,
        bot_name=bot_name,
        recurring_meeting_id=recurring_meeting_id,
        output_media_url=output_url,
    )

    print("Bot created!")
    print(f"  ID: {bot.id}")
    print(f"  Status: {bot.status}")
    print(f"  Recurring Meeting ID: {bot.recurring_meeting_id or 'None (isolated)'}")
    print()
    print(f"Check status: curl http://localhost:8000/api/bot/{bot.id}")


def main():
    parser = argparse.ArgumentParser(description="Create a Recall bot")
    parser.add_argument("meeting_url", help="Meeting URL (Zoom, Meet, Teams)")
    parser.add_argument("--project-id", default="default", help="Project ID")
    parser.add_argument("--bot-name", default="Recall", help="Bot name")
    parser.add_argument(
        "--recurring-meeting-id",
        help="Recurring meeting identifier for RAG context isolation. "
             "Meetings with the same ID share context. If not provided, "
             "the meeting is isolated with no RAG context."
    )

    args = parser.parse_args()

    asyncio.run(create_bot(
        args.meeting_url,
        args.project_id,
        args.bot_name,
        args.recurring_meeting_id,
    ))


if __name__ == "__main__":
    main()
