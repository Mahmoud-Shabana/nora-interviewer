# Nora Realtime Voice Protocol

Nora separates **speech transport** from **interview semantics**.

The browser demo can use Web Speech APIs, while production STT/TTS providers can feed the same lifecycle.

## Voice phases

```text
idle
  |
speech_started
  v
listening
  |
final transcript
  v
processing
  |
TTS starts
  v
speaking
  |
TTS completes
  v
idle
```

A completed interview transitions to `closed` after the final interviewer audio completes.

## WebSocket events

Client to Nora:

```json
{"type":"voice_speech_started","data":{}}
{"type":"voice_transcript_partial","data":{"text":"partial","confidence":null}}
{"type":"voice_transcript_final","data":{"text":"final answer","confidence":0.94}}
{"type":"voice_tts_started","data":{"turn_id":"..."}}
{"type":"voice_tts_completed","data":{"turn_id":"..."}}
{"type":"voice_tts_cancelled","data":{"turn_id":"..."}}
```

Nora emits `voice_state` snapshots in response and continues to emit normal `interviewer_turn`, `tool_opened`, and `interview_completed` events.

## Barge-in

If `voice_speech_started` arrives while the phase is `speaking`:

1. Nora increments the interruption counter.
2. The voice generation is incremented.
3. `voice_barge_in` is appended to the interview audit log.
4. The active TTS turn is recorded as cancelled.
5. The phase moves immediately to `listening`.

The generation number lets a future streaming provider discard stale audio chunks from an interrupted TTS stream.

## Timing

The coordinator records:

- speech start → final transcript;
- final transcript → interviewer response ready;
- response ready → TTS start.

These measurements stay separate because they correspond to different system components.

A future VoxRubric voice benchmark can therefore distinguish slow STT, slow reasoning, and slow TTS startup instead of reporting one opaque latency number.

## Provider boundary

The current browser demo is not the production speech engine.

Production adapters should provide:

- streaming audio ingestion;
- VAD;
- partial and final transcripts;
- streaming TTS chunks;
- cancellation;
- reconnect handling;
- backpressure;
- provider timestamps.

Those adapters feed the same lifecycle so interview logic, audit history, and evaluation remain provider-neutral.
