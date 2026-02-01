#!/usr/bin/env python3
"""CLI script to sync recurring meeting series index with Recall.ai."""
import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from server.rag.engine import get_rag_engine
from server.recall import get_recall_client


async def sync_recurring_meeting(recurring_meeting_id: str, force: bool = False) -> None:
    """Sync recurring meeting series index with Recall.ai transcripts."""
    print(f"Syncing recurring meeting series: {recurring_meeting_id}")

    # List bots for this recurring meeting series
    client = get_recall_client()
    bots = await client.list_recurring_meeting_bots(recurring_meeting_id)

    print(f"Found {len(bots)} bots in this meeting series")
    for bot in bots:
        status = "✓ transcript" if bot.transcript_url else "○ no transcript"
        print(f"  {bot.id[:8]}... {bot.status:10} {status}")

    print()

    # Sync index
    engine = get_rag_engine(recurring_meeting_id)
    if not engine:
        print("Error: No engine created (recurring_meeting_id is required)")
        return

    result = await engine.sync_index(force=force)

    print(f"Indexed {result['indexed']} new transcripts")
    print(f"Total bots: {result['total_bots']}")


async def list_meeting_series() -> None:
    """List all recurring meeting series (unique recurring_meeting_ids from bots)."""
    client = get_recall_client()
    bots, _ = await client.list_bots(limit=100)

    # Group by recurring_meeting_id
    series: dict[str, list] = {}
    isolated = 0
    for bot in bots:
        if bot.recurring_meeting_id:
            if bot.recurring_meeting_id not in series:
                series[bot.recurring_meeting_id] = []
            series[bot.recurring_meeting_id].append(bot)
        else:
            isolated += 1

    print(f"Recurring meeting series: {len(series)}")
    for s_id in sorted(series.keys()):
        count = len(series[s_id])
        print(f"  {s_id}: {count} bot(s)")

    if isolated:
        print(f"\nIsolated meetings (no recurring_meeting_id): {isolated}")


async def list_projects() -> None:
    """List all projects (unique project_ids from bots)."""
    client = get_recall_client()
    bots, _ = await client.list_bots(limit=100)

    projects = set(b.project_id for b in bots if b.project_id)
    print(f"Projects with bots: {len(projects)}")
    for p in sorted(projects):
        project_bots = [b for b in bots if b.project_id == p]
        print(f"  {p}: {len(project_bots)} bots")
        # Show recurring meeting breakdown
        series = set(b.recurring_meeting_id for b in project_bots if b.recurring_meeting_id)
        isolated = sum(1 for b in project_bots if not b.recurring_meeting_id)
        if series:
            print(f"    Meeting series: {', '.join(series)}")
        if isolated:
            print(f"    Isolated meetings: {isolated}")


def main():
    parser = argparse.ArgumentParser(
        description="Sync recurring meeting series index with Recall.ai",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Sync a specific recurring meeting series
  python sync_project.py monday-standup

  # Force re-index all transcripts in series
  python sync_project.py monday-standup --force

  # List all recurring meeting series
  python sync_project.py --list-series

  # List all projects and their meeting series
  python sync_project.py --list-projects
"""
    )
    parser.add_argument(
        "recurring_meeting_id",
        nargs="?",
        help="Recurring meeting ID to sync"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-index all transcripts"
    )
    parser.add_argument(
        "--list-series",
        action="store_true",
        help="List all recurring meeting series"
    )
    parser.add_argument(
        "--list-projects",
        action="store_true",
        help="List all projects and their meeting series"
    )

    args = parser.parse_args()

    if args.list_series:
        asyncio.run(list_meeting_series())
    elif args.list_projects:
        asyncio.run(list_projects())
    elif args.recurring_meeting_id:
        asyncio.run(sync_recurring_meeting(args.recurring_meeting_id, args.force))
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
