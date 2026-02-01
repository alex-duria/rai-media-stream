# Recall - Meeting Memory Bot

A voice-enabled meeting bot that remembers context across recurring meetings using RAG (Retrieval-Augmented Generation). Built on [Recall.ai](https://recall.ai) for meeting access and transcription.

---

## How to Interact with the Bot

Once the bot joins your meeting, you can interact with it using voice:

### Wake Word: "Recall"

**Option 1: Two-step (recommended for noisy meetings)**
1. Say: **"Recall"**
2. Bot responds: **"Yes?"**
3. Ask your question: **"What did we discuss about pricing last week?"**

**Option 2: Direct question**
- Say: **"Recall, tell me about the API integration we discussed"**
- Bot responds directly with the answer

### Voice Commands

The bot responds to natural leave requests containing keywords like "leave", "go away", "exit", "bye", "goodbye":

| Example | Action |
|---------|--------|
| "Recall, please leave" | Bot says goodbye and leaves |
| "Recall, can you leave the meeting now" | Bot says goodbye and leaves |
| "Recall, goodbye" | Bot says goodbye and leaves |
| "Recall" → "Yes?" → "leave" | Bot says goodbye and leaves |

### Chat Commands

Type in meeting chat:
- `remove`, `leave`, `exit`, or `bye` → Bot leaves the meeting

### Removing the Bot via API

```bash
curl -X POST https://your-app.example.com/api/bot/{bot_id}/leave
```

---

## Quick Start (Local Development)

### Prerequisites

- Python 3.11+
- Node.js 18+
- [ngrok](https://ngrok.com) account (free tier works)
- [Recall.ai API key](https://recall.ai)
- [OpenAI API key](https://platform.openai.com)

### Step 1: Install Dependencies

```bash
# Clone and enter the repository
git clone <repo-url>
cd rai-media-stream

# Install Python dependencies
pip install -r requirements.txt

# Install and build the client
cd client && npm install && npm run build && cd ..

# Copy environment template
cp .env.example .env
```

### Step 2: Configure Environment

Edit `.env` with your API keys:

```bash
OPENAI_API_KEY=sk-your-openai-api-key
RECALL_API_KEY=your-recall-api-key
RECALL_REGION=us-west-2
```

### Step 3: Start ngrok Tunnel

Recall.ai needs to reach your local server. Start ngrok:

```bash
ngrok http 8000
```

Copy the HTTPS URL (e.g., `https://abc123.ngrok.io`).

### Step 4: Update Environment URLs

Update `.env` with the ngrok URL:

```bash
CLIENT_URL=https://abc123.ngrok.io
SERVER_URL=https://abc123.ngrok.io
```

### Step 5: Start the Server

```bash
python -m uvicorn server.main:app --reload --host 0.0.0.0 --port 8000
```

### Step 6: Seed Sample Data (Optional)

Create sample meeting history for testing RAG:

```bash
python scripts/seed_transcripts.py
```

This creates sample meeting series:
- `monday-standup` - 2 past meetings
- `sprint-planning` - 1 past meeting
- `product-review` - 1 past meeting

### Step 7: Create a Bot and Join a Meeting

```bash
# With meeting memory (gets RAG context from past meetings in series)
python scripts/create_bot.py "https://zoom.us/j/123456789?pwd=xxx" \
  --project-id acme-corp \
  --recurring-meeting-id monday-standup

# Without meeting memory (isolated - no RAG context)
python scripts/create_bot.py "https://zoom.us/j/123456789?pwd=xxx" \
  --project-id acme-corp
```

### Step 8: Interact with the Bot

1. Wait for the bot to join your meeting
2. Say **"Recall"** - bot will respond with **"Yes?"**
3. Ask your question: **"What did we discuss last week?"**
4. Bot responds with information from past meetings in the same series

---

## Production Deployment

### Environment Variables

```bash
# Required
OPENAI_API_KEY=sk-...
RECALL_API_KEY=...
RECALL_REGION=us-west-2

# Set to your deployed URLs
CLIENT_URL=https://your-app.example.com
SERVER_URL=https://your-app.example.com

# Data persistence
DATA_DIR=/app/data
```

### Deploy to Railway / Render / Fly.io

1. Set environment variables in dashboard
2. Build command: `cd client && npm install && npm run build`
3. Start command: `gunicorn server.main:app -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:$PORT`

### Deploy with Docker

```dockerfile
FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt gunicorn

# Build client
COPY client/package*.json client/
RUN cd client && npm install
COPY client/ client/
RUN cd client && npm run build

COPY server/ server/
COPY scripts/ scripts/

ENV DATA_DIR=/app/data
VOLUME /app/data

EXPOSE 8000
CMD ["gunicorn", "server.main:app", "-w", "4", "-k", "uvicorn.workers.UvicornWorker", "--bind", "0.0.0.0:8000"]
```

### Configure Webhooks (Optional)

For automatic RAG indexing when meetings end:

1. Go to Recall.ai dashboard → Webhooks
2. Add endpoint: `https://your-app.example.com/webhooks/recall/`
3. Select events: `bot.status_change`, `transcript.done`

---

## Using the Bot (Deployed)

### Create a Bot via API

```bash
curl -X POST https://your-app.example.com/api/bot \
  -H "Content-Type: application/json" \
  -d '{
    "meeting_url": "https://zoom.us/j/123456789",
    "project_id": "acme-corp",
    "recurring_meeting_id": "monday-standup",
    "bot_name": "Recall"
  }'
```

### Create a Bot via CLI

```bash
python scripts/create_bot.py "https://zoom.us/j/123456789" \
  --project-id acme-corp \
  --recurring-meeting-id monday-standup
```

### Check Bot Status

```bash
curl https://your-app.example.com/api/bot/{bot_id}
```

### Remove Bot from Meeting

```bash
curl -X POST https://your-app.example.com/api/bot/{bot_id}/leave
```

---

## RAG Isolation Model

The `recurring_meeting_id` controls what context the bot can access:

| Scenario | RAG Behavior |
|----------|--------------|
| `recurring_meeting_id="monday-standup"` | Queries ONLY past "monday-standup" meetings |
| `recurring_meeting_id="sprint-planning"` | Queries ONLY past "sprint-planning" meetings |
| No `recurring_meeting_id` | **NO RAG context** - meeting is completely isolated |

This prevents context bleeding between different meeting types and ensures sensitive meetings stay private.

---

## Features

- **Meeting Memory**: Groups related meetings for isolated RAG context
- **Privacy-First**: Meetings without `recurring_meeting_id` get NO RAG context
- **Wake Word Activation**: Say "Recall" to get the bot's attention
- **Voice Commands**: Tell the bot to leave via voice
- **Real-time Transcription**: Low-latency streaming via Recall.ai
- **Action Item Detection**: Captures "remind me to...", "follow up on..."
- **Multi-Platform**: Zoom, Google Meet, Microsoft Teams

---

## API Reference

### Bot Management

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/bot` | Create a bot |
| `GET` | `/api/bot/{bot_id}` | Get bot status |
| `POST` | `/api/bot/{bot_id}/chat` | Send chat message into meeting |
| `POST` | `/api/bot/{bot_id}/leave` | Remove bot from meeting |

### RAG Context

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/projects/{id}/context?query=...&recurring_meeting_id=...` | Query RAG |
| `POST` | `/api/projects/{id}/sync?recurring_meeting_id=...` | Sync index |

### Webhooks

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/webhooks/recall/` | Recall.ai event webhook |
| `POST` | `/webhooks/recall/transcript` | Real-time transcript data |
| `POST` | `/webhooks/recall/chat` | Real-time chat messages |

---

## CLI Scripts

```bash
# Create a bot
python scripts/create_bot.py <meeting_url> \
  --project-id <id> \
  --recurring-meeting-id <series-id> \
  --bot-name "Recall"

# Seed sample meeting data
python scripts/seed_transcripts.py

# Sync project index
python scripts/sync_project.py <recurring_meeting_id> --force
```

---

## Architecture

```
Meeting Participants
         │
         ▼
┌─────────────────┐
│   Recall Bot    │ ← Joins meeting, captures audio
└────────┬────────┘
         │ Real-time transcription
         ▼
┌─────────────────┐
│  Output Media   │ ← Webpage rendered as bot's "camera"
│  (Client)       │    Shows conversation + thinking process
└────────┬────────┘
         │ WebSocket (transcripts → server, audio ← server)
         ▼
┌─────────────────┐
│  FastAPI Server │ ← RAG queries, AI response generation
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Recall.ai API  │ ← Transcript storage, bot management
│  OpenAI API     │ ← GPT-4o-mini for responses, TTS for audio
└─────────────────┘
```

---

## Configuration

| Variable | Description | Default |
|----------|-------------|---------|
| `OPENAI_API_KEY` | OpenAI API key | Required |
| `RECALL_API_KEY` | Recall.ai API key | Required |
| `RECALL_REGION` | Recall.ai region | `us-west-2` |
| `CLIENT_URL` | Public URL for output media | `http://localhost:5173` |
| `SERVER_URL` | Public URL for server | `http://localhost:8000` |
| `DATA_DIR` | Data storage directory | `data` |
| `RAG_SIMILARITY_THRESHOLD` | Min similarity score | `0.15` |
| `RAG_TOP_K` | Max results per query | `5` |

---

## Recall.ai Features Used

| Feature | Usage |
|---------|-------|
| **Bot Creation** | Custom metadata for project/meeting isolation |
| **Output Media** | Webpage as bot's camera + audio injection |
| **Real-time Transcription** | Low-latency streaming transcription |
| **Perfect Diarization** | Accurate speaker attribution |
| **In-Meeting Chat** | Welcome message, "remove" command |
| **Automatic Leave** | Smart timeouts for waiting room, silence, empty meeting |
| **Speaker Timeline** | Post-meeting speaker events |
| **Webhooks** | `transcript.done`, `bot.status_change` |

---

## License

MIT
