"""Seed sample transcripts for testing RAG functionality with recurring meeting isolation."""
import sys
from pathlib import Path
from datetime import datetime, timedelta

import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent))

from openai import OpenAI
from server.config import get_settings
from server.rag.engine import VectorCache, Chunk

# Sample meeting transcripts with recurring_meeting_id for isolation testing
# Meetings with the same recurring_meeting_id share context; different IDs are isolated
SAMPLE_MEETINGS = [
    # Monday Standup Series - Week 1
    {
        "bot_id": "sample-standup-week1",
        "title": "Monday Standup",
        "date": datetime.now() - timedelta(days=14),
        "recurring_meeting_id": "monday-standup",
        "transcript": """
Alex: Yesterday I finished the WebSocket implementation for real-time updates.
Jordan: Nice! I'm still working on the database migration scripts.
Alex: We decided to use PostgreSQL instead of MySQL for better JSON support.
Jordan: Makes sense. The team agreed on using FastAPI for the backend.
Alex: Remind me to set up the CI/CD pipeline for the staging environment.
Jordan: I'll follow up with DevOps about the Kubernetes cluster setup.
"""
    },
    # Monday Standup Series - Week 2
    {
        "bot_id": "sample-standup-week2",
        "title": "Monday Standup",
        "date": datetime.now() - timedelta(days=7),
        "recurring_meeting_id": "monday-standup",
        "transcript": """
Alex: The CI/CD pipeline is now set up and running.
Jordan: Great! The database migration is complete too.
Alex: We need to review the API rate limiting before launch.
Jordan: I'll handle that. Also, the JWT token expiry is set to 24 hours.
Alex: Perfect. Let's make sure the monitoring dashboards are ready.
Jordan: Action item: I'll set up Grafana alerts by Wednesday.
"""
    },
    # Sprint Planning Series - separate from standups
    {
        "bot_id": "sample-planning-1",
        "title": "Sprint Planning",
        "date": datetime.now() - timedelta(days=10),
        "recurring_meeting_id": "sprint-planning",
        "transcript": """
Sarah: Let's discuss the Q4 roadmap. We need to finalize the pricing strategy.
Mike: I think we should go with the tiered pricing model we discussed.
Sarah: Agreed. The enterprise tier at $99/month seems reasonable.
Mike: We also need to circle back on the Redis configuration for caching.
Sarah: Right, remind me to review the deployment scripts before we launch.
Mike: Action item: I'll sync with Lisa on the marketing copy by Wednesday.
"""
    },
    # Product Review Series - completely separate context
    {
        "bot_id": "sample-product-review-1",
        "title": "Product Review",
        "date": datetime.now() - timedelta(days=5),
        "recurring_meeting_id": "product-review",
        "transcript": """
Emma: The user feedback on the new dashboard has been positive.
Chris: We saw a 40% increase in daily active users after the redesign.
Emma: The mobile app launch is scheduled for next month.
Chris: Action item: prepare the app store screenshots by Friday.
Emma: We need to finalize the onboarding flow for new users.
Chris: The A/B test showed the simplified signup converts 25% better.
"""
    },
    # Isolated meeting (no recurring_meeting_id) - for testing isolation
    {
        "bot_id": "sample-isolated-meeting",
        "title": "One-off Strategy Discussion",
        "date": datetime.now() - timedelta(days=2),
        "recurring_meeting_id": None,  # Isolated - no RAG context
        "transcript": """
CEO: We need to discuss the acquisition offer from Acme Corp.
CFO: The valuation seems fair but we should review the terms carefully.
CEO: This is confidential. Don't share details with anyone outside this room.
CFO: Agreed. I'll prepare the financial analysis by end of week.
"""
    },
]


def seed_recurring_meeting(recurring_meeting_id: str, meetings: list):
    """Seed transcripts for a specific recurring meeting series."""
    settings = get_settings()
    openai = OpenAI(api_key=settings.openai_api_key)

    cache_path = Path(settings.data_dir) / "meetings" / recurring_meeting_id / "vectors.json"
    cache = VectorCache(project_id=recurring_meeting_id)

    print(f"\nSeeding recurring meeting: {recurring_meeting_id}")
    print(f"Cache path: {cache_path}")

    for meeting in meetings:
        print(f"  Processing: {meeting['title']} ({meeting['date'].strftime('%Y-%m-%d')})...")

        # Chunk the transcript
        lines = [line.strip() for line in meeting["transcript"].strip().split("\n") if line.strip()]

        # Group into chunks of ~3-4 lines
        chunks = []
        for i in range(0, len(lines), 3):
            chunk_text = " ".join(lines[i:i+3])
            chunks.append(chunk_text)

        # Get embeddings
        response = openai.embeddings.create(
            model=settings.openai_embedding_model,
            input=chunks,
        )

        embeddings = [
            np.array(item.embedding, dtype=np.float32)
            for item in sorted(response.data, key=lambda x: x.index)
        ]

        # Create chunks with recurring_meeting_id
        for text, emb in zip(chunks, embeddings):
            cache.chunks.append(Chunk(
                bot_id=meeting["bot_id"],
                text=text,
                embedding=emb,
                meeting_title=meeting["title"],
                meeting_date=meeting["date"],
                recurring_meeting_id=recurring_meeting_id,
            ))

        cache.indexed_bots.add(meeting["bot_id"])
        print(f"    Added {len(chunks)} chunks")

    # Save cache
    cache.save(cache_path)
    print(f"  Saved {len(cache.chunks)} total chunks")


def seed_all():
    """Seed all sample meeting series."""
    print("=" * 60)
    print("Seeding sample transcripts with recurring meeting isolation")
    print("=" * 60)

    # Group meetings by recurring_meeting_id
    meetings_by_series: dict[str, list] = {}
    isolated_meetings = []

    for meeting in SAMPLE_MEETINGS:
        recurring_id = meeting.get("recurring_meeting_id")
        if recurring_id:
            if recurring_id not in meetings_by_series:
                meetings_by_series[recurring_id] = []
            meetings_by_series[recurring_id].append(meeting)
        else:
            isolated_meetings.append(meeting)

    # Seed each meeting series
    for recurring_id, meetings in meetings_by_series.items():
        seed_recurring_meeting(recurring_id, meetings)

    # Report isolated meetings (not seeded - they have no RAG context)
    if isolated_meetings:
        print(f"\n{len(isolated_meetings)} isolated meeting(s) (no recurring_meeting_id, no RAG):")
        for m in isolated_meetings:
            print(f"  - {m['title']} ({m['bot_id']})")

    print("\n" + "=" * 60)
    print("Done!")
    print(f"Seeded {len(meetings_by_series)} meeting series:")
    for series_id, meetings in meetings_by_series.items():
        print(f"  - {series_id}: {len(meetings)} meeting(s)")
    print("\nTo test:")
    print("  # Create bot WITH recurring_meeting_id (gets RAG context from series):")
    print('  python scripts/create_bot.py "https://zoom.us/j/123" --recurring-meeting-id monday-standup')
    print("\n  # Create bot WITHOUT recurring_meeting_id (isolated, no RAG):")
    print('  python scripts/create_bot.py "https://zoom.us/j/456"')


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--help":
        print("Usage: python seed_transcripts.py")
        print("\nSeeds sample transcripts for testing recurring meeting RAG isolation.")
        print("Each recurring_meeting_id gets its own isolated vector cache.")
        sys.exit(0)

    seed_all()
