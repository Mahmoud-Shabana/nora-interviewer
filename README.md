# Nora Interviewer

A production-oriented nucleus for **real-time, adaptive AI interviews**. Nora handles interview state, competency coverage, traceable follow-ups, WebSocket interaction, consent gates, and export into the open VoxRubric evaluation format.

The repository intentionally separates **conversation orchestration** from **speech providers**, **LLM providers**, and **candidate evaluation** so the system can evolve without turning into a provider-specific demo.

## Current v0.2

- FastAPI REST API
- browser interview room at `/`
- real-time WebSocket interview protocol
- optional browser speech recognition + speech synthesis demo
- structured LLM brain with an OpenAI-compatible provider adapter
- deterministic fallback if the model/provider fails
- explicit interview state machine
- adaptive follow-up linkage through `parent_turn_id`
- competency coverage tracking
- mandatory AI/transcript consent gate
- provider protocols for LLM brain, STT, and TTS
- deterministic development brain for reproducible tests
- VoxRubric-compatible trace export
- test suite and CI-ready package

## Run

```bash
python -m pip install -e '.[dev]'
pytest
uvicorn nora_interviewer.api:app --reload

# then open http://localhost:8000
```

Then create a job, create a consented session, and connect to:

```text
ws://localhost:8000/v1/ws/interviews/{session_id}
```

Client event:

```json
{"type": "candidate_text", "text": "I redesigned the queue consumer and reduced p95 latency..."}
```

Server event:

```json
{
  "type": "interviewer_turn",
  "data": {
    "speaker": "interviewer",
    "text": "Could you make that more concrete...",
    "parent_turn_id": "candidate-turn-id",
    "competency_tags": ["distributed_systems"]
  }
}
```

## LLM mode

The default is deterministic `rule` mode so a fresh clone runs with no credentials.

To use an OpenAI-compatible chat-completions server:

```bash
export NORA_BRAIN_MODE=openai-compatible
export NORA_LLM_BASE_URL=https://your-provider.example/v1
export NORA_LLM_MODEL=your-model
export NORA_LLM_API_KEY=...
uvicorn nora_interviewer.api:app --reload
```

The LLM returns only a structured action, candidate-facing text, known competency IDs, and a reason. Nora—not the model—owns session state and follow-up parent IDs. Unknown competency IDs are rejected. Candidate answers are explicitly treated as untrusted data in the system prompt.

## Browser voice demo

When supported by the browser, the interview room can use browser-native speech recognition to fill the candidate answer box and speech synthesis to read Nora's questions aloud. This is deliberately a demo transport layer; production voice should use streaming STT/TTS providers with measured end-to-end latency, cancellation, barge-in, and reconnect handling.

## Container run

```bash
docker compose up --build
```

Then open `http://localhost:8000`.

## Why the rule-based brain exists

It is a **test double**, not the product intelligence. It makes session behavior reproducible in CI while the production `InterviewBrain` can be backed by any capable model. The public contract stays the same either way.

## Real voice path

The WebSocket transport is designed to grow into this event flow:

```text
microphone -> audio chunks -> VAD/STT -> partial transcript
                                  |
                                  v
                           InterviewBrain
                                  |
                                  v
                            response text
                                  |
                                  v
                              TTS stream
                                  |
                                  v
                               browser
```

The `SpeechToTextProvider` and `TextToSpeechProvider` protocols are already isolated for this purpose. The browser demo provides immediate voice interaction without a backend speech key; production implementations should still support barge-in, cancellation, backpressure, reconnects, and measured end-to-end latency.

## Evaluation path

Nora does **not** silently decide who gets hired. Session traces export to VoxRubric so scoring behavior can be tested separately for grounding, coverage, consistency, latency, multilingual robustness, and other metrics.

## Safety baseline

Do not score protected or sensitive traits, facial appearance, attractiveness, accent prestige, or inferred emotion. Keep job-related rubrics explicit, candidate data access-controlled, and hiring decisions under accountable human review.

See `docs/ARCHITECTURE.md` for system boundaries.
