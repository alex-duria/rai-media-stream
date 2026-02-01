# Recall - Media Stream Agent with Persistent Meeting Context

An AI agent that lives inside your recurring meetings and maintains persistent memory across the entire product lifecycle. Discovery conversations inform sprint planning. Last quarter's architectural decisions are instantly accessible during implementation. Context compounds instead of evaporating.

Built on [Recall.ai](https://recall.ai) for meeting access and real-time transcription.

---

## Why This Matters

**Meetings are where decisions happen. But decisions don't stay in meetings.**

Product teams run dozens of recurring meetings: standups, sprint planning, design reviews, stakeholder syncs, retros. Each meeting builds on the last—but the context doesn't carry forward. Teams waste time re-explaining decisions, re-debating settled questions, and onboarding people who missed critical conversations.

**This agent solves that by giving your meeting series a persistent memory.**

- **Continuity across product cycles**: What was discussed in discovery is accessible during development. Decisions from Q1 planning inform Q3 execution.
- **Institutional knowledge that doesn't evaporate**: Why did we choose this architecture? What were the tradeoffs? The answer isn't buried in someone's notes—it's instantly accessible.
- **Faster onboarding**: New team members can query months of context without scheduling "catch-up" meetings.
- **No more "meeting about the meeting"**: Stop spending the first 10 minutes recapping what happened last time.

```
Sprint 1 Planning  ─┐
Sprint 1 Retro     ─┼─► All indexed under "project-alpha-sprints"
Sprint 2 Planning  ─┤
Sprint 2 Retro     ─┤
        ...        ─┤
Sprint N Planning  ─┘   ← Bot joins with full context of every previous sprint
```

---

## Recall.ai Features Used

| Feature | How We Use It |
|---------|---------------|
| **Bot Metadata** | Store `project_id` and `recurring_meeting_id` to group related meetings |
| **Metadata Filtering** | Query `GET /bot/?metadata__recurring_meeting_id=X` to find all meetings in a series |
| **Output Media** | Render a webpage as the bot's "camera" - displays conversation + thinking process |
| **Audio Injection** | Play AI-generated speech (OpenAI TTS) into the meeting via output media |
| **Real-time Transcription** | Stream transcripts via webhook for immediate processing |
| **Transcript Download** | Fetch completed transcripts from past meetings for RAG indexing |
| **In-Meeting Chat** | Send welcome message, respond to "remove" command |
| **Automatic Leave** | Configure timeouts for waiting room, empty meeting, silence |

---

## How It Works

```
┌─────────────────────────────────────────────────────────────────────┐
│                         MEETING                                      │
│                                                                      │
│   Participant: "Recall, what did we decide about the API pricing?"  │
│                              │                                       │
└──────────────────────────────┼───────────────────────────────────────┘
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      RECALL.AI BOT                                   │
│                                                                      │
│   • Captures audio, runs real-time transcription                    │
│   • Renders "output media" webpage as bot's camera feed             │
│   • Streams transcript to our server via webhook                    │
│                              │                                       │
└──────────────────────────────┼───────────────────────────────────────┘
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      OUR SERVER                                      │
│                                                                      │
│   1. Detect wake word "Recall" in transcript                        │
│   2. Query Recall API: GET /bot/?metadata__recurring_meeting_id=X   │
│   3. Fetch transcripts from past meetings in series                 │
│   4. RAG search: find relevant chunks from meeting history          │
│   5. Generate response with GPT-4o-mini + context                   │
│   6. Convert to speech with OpenAI TTS                              │
│   7. Send audio back to output media page                           │
│                              │                                       │
└──────────────────────────────┼───────────────────────────────────────┘
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      OUTPUT MEDIA PAGE                               │
│                                                                      │
│   • Plays audio response into meeting                               │
│   • Shows conversation transcript                                   │
│   • Displays RAG search results (which meetings, similarity scores) │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Ideas for Extension

This agent is a foundation. Here's what you could build on top of it:

### 1. Automated Meeting Artifacts
Generate and distribute summaries, action items, and decision logs after each meeting. Push them to Slack, email, or Notion automatically. The transcripts are already there—just add a post-meeting processing pipeline.

### 2. Project Management Integration
Connect action item detection to Jira, Linear, or Asana. When someone says "we need to update the API docs before launch," automatically create a ticket with context from the conversation.

### 3. Async Query Interface
Build a Slack bot or web dashboard that lets team members query meeting history outside of meetings. "What did we decide about the pricing model?" shouldn't require joining a call.

### 4. Pre-Meeting Intelligence
Generate briefing docs before meetings start. Pull relevant context from past meetings, open action items, and recent decisions. Participants arrive prepared instead of spending time getting up to speed.

### 5. Cross-Project Pattern Detection
Analyze meeting data across multiple project series to surface organizational patterns. Which projects have the most blockers? Where are decisions getting revisited? What topics consume the most meeting time?

### 6. Custom Domain Agents
Swap in specialized AI personas with domain knowledge. A legal review agent that flags compliance concerns. A technical architecture agent that references your design docs. The meeting interface stays the same—the intelligence layer adapts.

**Explore what's possible**: [Recall.ai API Documentation](https://docs.recall.ai/)

---

## Quick Start (Local Development)

### Prerequisites

- Python 3.11+
- Node.js 18+
- [ngrok](https://ngrok.com) (free tier works)
- [Recall.ai API key](https://recall.ai)
- [OpenAI API key](https://platform.openai.com)

### Setup

```bash
# Install dependencies
pip install -r requirements.txt
cd client && npm install && npm run build && cd ..

# Configure environment
cp .env.example .env
# Edit .env with your API keys

# Start ngrok (Recall.ai needs to reach your server)
ngrok http 8000
# Copy the HTTPS URL and update CLIENT_URL and SERVER_URL in .env

# Start server
python -m uvicorn server.main:app --reload --port 8000
```

### Create a Bot

```bash
# With persistent context (RAG enabled)
python scripts/create_bot.py "https://zoom.us/j/123456789" \
  --project-id acme-corp \
  --recurring-meeting-id monday-standup

# Without persistent context (isolated meeting)
python scripts/create_bot.py "https://zoom.us/j/123456789" \
  --project-id acme-corp
```

### Seed Sample Data (Optional)

Create fake meeting history to test RAG without waiting for real meetings:

```bash
python scripts/seed_transcripts.py
```

---

## Interacting with the Bot

### Voice Commands

**Wake word: "Recall"**

| You Say | Bot Does |
|---------|----------|
| "Recall" | Responds "Yes?" and waits for your question |
| "Recall, what did we discuss about X?" | Searches meeting history and responds |
| "Recall, please leave" | Says goodbye and leaves the meeting |
| "Recall, goodbye" | Says goodbye and leaves the meeting |

### Chat Commands

Type in meeting chat:
- `remove`, `leave`, `exit`, `bye` → Bot leaves the meeting

### API

```bash
# Remove bot
curl -X POST https://your-server/api/bot/{bot_id}/leave
```

---

## RAG Isolation

The `recurring_meeting_id` controls what context the bot can access:

| Configuration | Behavior |
|---------------|----------|
| `recurring_meeting_id="monday-standup"` | Queries only past "monday-standup" meetings |
| `recurring_meeting_id="sprint-planning"` | Queries only past "sprint-planning" meetings |
| No `recurring_meeting_id` | No RAG context - meeting is completely isolated |

This prevents context bleeding between different meeting types.

---

## Project Structure

```
server/
├── main.py                 # FastAPI app, WebSocket endpoint
├── websocket_handler.py    # Handles output media WebSocket connection
├── config.py               # Environment configuration
├── constants.py            # Wake words, leave keywords, etc.
├── models.py               # Pydantic models
├── state.py                # In-memory state (active bots, handlers)
├── recall/
│   └── client.py           # Recall.ai API client
├── rag/
│   └── engine.py           # Vector cache, embedding, search
├── ai/
│   └── responder.py        # GPT-4o-mini responses, TTS
├── memory/
│   └── action_items.py     # Action item detection
└── routers/
    ├── bots.py             # Bot CRUD endpoints
    ├── projects.py         # RAG context endpoints
    └── webhooks.py         # Recall.ai webhook handlers

client/
└── src/
    └── main.ts             # Output media page (bot's camera)

scripts/
├── create_bot.py           # CLI to create bots
├── seed_transcripts.py     # Generate sample meeting data
└── sync_project.py         # Manually sync RAG index
```

---

## API Reference

### Bot Management

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/bot` | Create a bot |
| `GET` | `/api/bot/{bot_id}` | Get bot status |
| `POST` | `/api/bot/{bot_id}/leave` | Remove bot from meeting |
| `POST` | `/api/bot/{bot_id}/chat` | Send chat message |

### RAG Context

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/projects/{id}/context?query=...&recurring_meeting_id=...` | Query RAG |
| `POST` | `/api/projects/{id}/sync?recurring_meeting_id=...` | Force sync index |

### Webhooks (for Recall.ai)

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/webhooks/recall/` | Bot status changes |
| `POST` | `/webhooks/recall/transcript` | Real-time transcript data |
| `POST` | `/webhooks/recall/chat` | Chat message events |

---

## Configuration

| Variable | Description | Default |
|----------|-------------|---------|
| `OPENAI_API_KEY` | OpenAI API key | Required |
| `RECALL_API_KEY` | Recall.ai API key | Required |
| `RECALL_REGION` | Recall.ai region | `us-west-2` |
| `CLIENT_URL` | Public URL for output media | `http://localhost:5173` |
| `SERVER_URL` | Public URL for webhooks | `http://localhost:8000` |
| `DATA_DIR` | Data storage directory | `data` |
| `RAG_SIMILARITY_THRESHOLD` | Min similarity for results | `0.20` |
| `RAG_TOP_K` | Max results per query | `5` |

---

## License

MIT
