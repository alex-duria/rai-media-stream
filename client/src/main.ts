/**
 * Project Memory Agent - Output Media Client
 *
 * This page is rendered as the bot's "camera" in the meeting via Recall.ai's
 * output_media feature. It handles:
 *
 * 1. Connecting to Recall's transcript WebSocket for real-time speech-to-text
 * 2. Forwarding transcripts to our server for AI processing
 * 3. Receiving and playing AI-generated audio responses
 * 4. Displaying conversation and RAG context visualization
 */

// --- Type Definitions ---

interface WSMessage {
  type: string;
  data: Record<string, unknown>;
}

interface RecallTranscriptMessage {
  transcript?: {
    original_transcript_id: number;
    is_final: boolean;
    speaker: string;
    speaker_id: number;
    words: Array<{ text: string; start_time: number; end_time: number }>;
    language: string;
  };
}

interface RAGResult {
  text: string;
  meeting: string;
  date: string;
  similarity: number;
}

// --- Main Application ---

class OutputMediaApp {
  private serverWs: WebSocket | null = null;
  private recallWs: WebSocket | null = null;
  private audioQueue: string[] = [];
  private isPlaying = false;
  private projectId: string;
  private botId: string | null;
  private recurringMeetingId: string | null;
  private lastTranscriptId: number | null = null;  // Track to prevent duplicates
  private recentFinalTexts: string[] = [];  // Track recent final texts for deduplication

  constructor() {
    this.projectId = this.getParam('project_id') || 'default';
    this.botId = this.getParam('bot_id');
    this.recurringMeetingId = this.getParam('recurring_meeting_id');
    console.log('Config:', { projectId: this.projectId, botId: this.botId, recurringMeetingId: this.recurringMeetingId });
    this.init();
  }

  private getParam(name: string): string | null {
    return new URLSearchParams(window.location.search).get(name);
  }

  private init(): void {
    this.updateStatus('Connecting...');
    this.connectToServer();
    this.connectToRecallTranscript();
  }

  // --- Server WebSocket (for AI responses) ---

  private getServerWsUrl(): string {
    // ws_host is passed from server to tell us where to connect back
    const wsHost = this.getParam('ws_host') || window.location.host;
    const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    let url = `${wsProtocol}//${wsHost}/ws/${this.projectId}`;

    // Build query params
    const params = new URLSearchParams();
    if (this.botId) {
      params.set('bot_id', this.botId);
    }
    if (this.recurringMeetingId) {
      params.set('recurring_meeting_id', this.recurringMeetingId);
    }

    const queryString = params.toString();
    if (queryString) {
      url += `?${queryString}`;
    }

    return url;
  }

  private connectToServer(): void {
    try {
      const url = this.getServerWsUrl();
      console.log('Connecting to server:', url);
      this.serverWs = new WebSocket(url);

      this.serverWs.onopen = () => {
        console.log('Server WebSocket connected');
        this.updateStatus('Connected to server');
      };

      this.serverWs.onmessage = (event) => {
        this.handleServerMessage(JSON.parse(event.data));
      };

      this.serverWs.onclose = () => {
        console.log('Server WebSocket closed, reconnecting...');
        setTimeout(() => this.connectToServer(), 3000);
      };

      this.serverWs.onerror = (error) => {
        console.error('Server WebSocket error:', error);
      };
    } catch (error) {
      console.error('Failed to connect to server:', error);
      setTimeout(() => this.connectToServer(), 3000);
    }
  }

  // --- Recall Transcript WebSocket ---

  private connectToRecallTranscript(): void {
    try {
      // This endpoint is available to output media pages running inside Recall's bot
      const url = 'wss://meeting-data.bot.recall.ai/api/v1/transcript';
      console.log('Connecting to Recall transcript:', url);

      this.recallWs = new WebSocket(url);

      this.recallWs.onopen = () => {
        console.log('Recall transcript connected');
        this.updateStatus('Listening for speech...');
      };

      this.recallWs.onmessage = (event) => {
        this.handleRecallTranscript(JSON.parse(event.data));
      };

      this.recallWs.onclose = () => {
        console.log('Recall transcript closed, reconnecting...');
        setTimeout(() => this.connectToRecallTranscript(), 3000);
      };

      this.recallWs.onerror = (error) => {
        console.error('Recall transcript error:', error);
      };
    } catch (error) {
      console.error('Failed to connect to Recall transcript:', error);
      setTimeout(() => this.connectToRecallTranscript(), 3000);
    }
  }

  private handleRecallTranscript(msg: RecallTranscriptMessage): void {
    const transcript = msg.transcript;
    if (!transcript?.words?.length) return;

    const transcriptId = transcript.original_transcript_id;
    const text = transcript.words.map((w) => w.text).join(' ');
    const speaker = transcript.speaker || 'Unknown';
    const isFinal = transcript.is_final;

    // Skip if we've already processed this final transcript (by ID)
    if (isFinal && transcriptId === this.lastTranscriptId) {
      console.log(`Skipping duplicate transcript ID ${transcriptId}`);
      return;
    }

    // Skip if we've seen this exact text recently (text-based dedup)
    if (isFinal) {
      const normalizedText = text.toLowerCase().trim();
      if (this.recentFinalTexts.includes(normalizedText)) {
        console.log(`Skipping duplicate text: ${text.slice(0, 30)}...`);
        return;
      }
      // Track this text, keep last 5
      this.recentFinalTexts.push(normalizedText);
      if (this.recentFinalTexts.length > 5) {
        this.recentFinalTexts.shift();
      }
      this.lastTranscriptId = transcriptId;
    }

    console.log(`[${speaker}] ${text} (final: ${isFinal}, id: ${transcriptId})`);

    // Display locally - only show final transcripts to avoid clutter
    // Interim transcripts update the "current" element in place
    this.addTranscript(speaker, text, isFinal);

    // Forward to server for AI processing (only final to reduce noise)
    if (isFinal && this.serverWs?.readyState === WebSocket.OPEN) {
      this.serverWs.send(
        JSON.stringify({
          type: 'transcript',
          speaker,
          text,
          is_final: isFinal,
        })
      );
    }
  }

  // --- Server Message Handling ---

  private handleServerMessage(msg: WSMessage): void {
    switch (msg.type) {
      case 'transcript':
        // Bot's response transcript
        this.addTranscript(
          (msg.data.speaker as string) || 'assistant',
          msg.data.text as string,
          msg.data.is_final as boolean
        );
        break;

      case 'audio':
        // Queue audio for playback
        if (msg.data.audio) {
          this.queueAudio(msg.data.audio as string);
        }
        break;

      case 'thinking':
        // RAG context visualization
        this.showThinkingStep(
          msg.data.step as string,
          msg.data.message as string,
          msg.data.data as Record<string, unknown> | undefined
        );
        break;

      case 'error':
        this.showError((msg.data.error as string) || 'Unknown error');
        break;

      default:
        console.log('Unknown message type:', msg.type);
    }
  }

  // --- Audio Playback ---

  private queueAudio(base64Audio: string): void {
    this.audioQueue.push(base64Audio);
    if (!this.isPlaying) {
      this.playNextAudio();
    }
  }

  private async playNextAudio(): Promise<void> {
    if (this.audioQueue.length === 0) {
      this.isPlaying = false;
      return;
    }

    this.isPlaying = true;
    const base64Audio = this.audioQueue.shift()!;

    try {
      // Decode base64 to binary
      const binaryString = atob(base64Audio);
      const bytes = new Uint8Array(binaryString.length);
      for (let i = 0; i < binaryString.length; i++) {
        bytes[i] = binaryString.charCodeAt(i);
      }

      const blob = new Blob([bytes], { type: 'audio/mp3' });
      const audioUrl = URL.createObjectURL(blob);
      const audio = new Audio(audioUrl);

      this.showSpeaking(true);

      audio.onended = () => {
        this.showSpeaking(false);
        URL.revokeObjectURL(audioUrl);
        this.playNextAudio();
      };

      audio.onerror = () => {
        console.error('Audio playback error');
        this.showSpeaking(false);
        URL.revokeObjectURL(audioUrl);
        this.playNextAudio();
      };

      await audio.play();
    } catch (error) {
      console.error('Failed to play audio:', error);
      this.showSpeaking(false);
      this.playNextAudio();
    }
  }

  // --- UI Updates ---

  private updateStatus(message: string): void {
    const el = document.getElementById('status');
    if (el) el.textContent = message;
  }

  private addTranscript(speaker: string, text: string, isFinal: boolean): void {
    const container = document.getElementById('transcripts');
    if (!container) return;

    let currentEl = container.querySelector('.transcript-current') as HTMLDivElement;

    if (isFinal || !currentEl) {
      // Create new transcript element
      const div = document.createElement('div');
      div.className = `transcript ${speaker === 'assistant' ? 'assistant' : 'user'}`;
      div.innerHTML = `<span class="speaker">${speaker}:</span> <span class="text">${text}</span>`;
      container.appendChild(div);

      if (currentEl) {
        currentEl.classList.remove('transcript-current');
      }

      if (!isFinal) {
        div.classList.add('transcript-current');
      }
    } else {
      // Update existing interim transcript
      const textEl = currentEl.querySelector('.text');
      if (textEl) textEl.textContent = text;
    }

    // Always scroll to bottom - scroll the parent panel-content, not the transcripts div
    requestAnimationFrame(() => {
      const scrollContainer = container.parentElement;
      if (scrollContainer) {
        scrollContainer.scrollTop = scrollContainer.scrollHeight;
      }
    });
  }

  private showThinkingStep(
    step: string,
    message: string,
    data?: Record<string, unknown>
  ): void {
    const container = document.getElementById('thinking-steps');
    if (!container) return;

    // Clear on new processing cycle
    if (step === 'processing') {
      container.innerHTML = '';
    }

    const stepDiv = document.createElement('div');
    stepDiv.className = `thinking-step step-${step}`;

    // Icon mapping for different steps
    const icons: Record<string, string> = {
      processing: '🔍',
      context: '📚',
      generating: '🤖',
      complete: '✓',
    };

    const icon = icons[step] || '•';

    switch (step) {
      case 'processing':
        stepDiv.innerHTML = `<span class="icon">${icon}</span> ${message}`;
        if (data?.query) {
          const queryDiv = document.createElement('div');
          queryDiv.className = 'context-query';
          queryDiv.innerHTML = `<strong>Query:</strong> "${this.escapeHtml(data.query as string)}"`;
          stepDiv.appendChild(queryDiv);
        }
        container.appendChild(stepDiv);
        break;

      case 'context':
        stepDiv.innerHTML = `<span class="icon">${icon}</span> ${message}`;
        container.appendChild(stepDiv);

        // Show message if no results
        if (data?.message) {
          const msgDiv = document.createElement('div');
          msgDiv.className = 'context-message';
          msgDiv.textContent = data.message as string;
          container.appendChild(msgDiv);
        }

        // Show RAG results if present
        if (data?.results) {
          const results = data.results as RAGResult[];
          if (results.length > 0) {
            // Query
            if (data.query) {
              const queryDiv = document.createElement('div');
              queryDiv.className = 'context-query';
              queryDiv.innerHTML = `<strong>Searched:</strong> "${this.escapeHtml(data.query as string)}"`;
              container.appendChild(queryDiv);
            }

            // Results
            for (const r of results) {
              const div = document.createElement('div');
              div.className = 'rag-result';
              div.innerHTML = `
                <div class="result-meta">
                  <strong>${r.meeting}</strong> (${r.date})
                  <span class="similarity">${(r.similarity * 100).toFixed(0)}% match</span>
                </div>
                <div class="result-text">${this.escapeHtml(r.text)}</div>
              `;
              container.appendChild(div);
            }
          }
        }
        break;

      case 'generating':
        stepDiv.innerHTML = `<span class="icon">${icon}</span> ${message}`;
        if (data?.has_context) {
          const ctxDiv = document.createElement('div');
          ctxDiv.className = 'context-info';
          ctxDiv.textContent = `Using ${data.context_length} chars of context`;
          stepDiv.appendChild(ctxDiv);
        }
        container.appendChild(stepDiv);
        break;

      case 'complete':
        stepDiv.innerHTML = `<span class="icon">${icon}</span> ${message}`;
        container.appendChild(stepDiv);
        break;

      default:
        // Generic step display
        stepDiv.innerHTML = `<span class="icon">${icon}</span> ${message}`;
        container.appendChild(stepDiv);
    }

    // Scroll the parent panel-content
    const scrollContainer = container.parentElement;
    if (scrollContainer) {
      scrollContainer.scrollTop = scrollContainer.scrollHeight;
    }
  }

  private escapeHtml(text: string): string {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }

  private showError(error: string): void {
    console.error('Error:', error);
    const el = document.getElementById('error');
    if (el) {
      el.textContent = error;
      el.style.display = 'block';
      setTimeout(() => {
        el.style.display = 'none';
      }, 5000);
    }
  }

  private showSpeaking(speaking: boolean): void {
    const indicator = document.getElementById('speaking-indicator');
    if (indicator) {
      indicator.style.display = speaking ? 'block' : 'none';
    }
  }
}

// Initialize on DOM ready
document.addEventListener('DOMContentLoaded', () => {
  new OutputMediaApp();
});
