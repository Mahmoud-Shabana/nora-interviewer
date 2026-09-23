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


## Production streaming transport

Nora now includes vendor-neutral WebSocket adapters for both directions:

- `nora.stt.v1` for candidate audio → partial/final transcripts;
- `nora.tts.v1` for interviewer text → streaming audio.

The adapters deliberately define Nora-owned transport contracts instead of coupling the orchestration layer to one speech vendor.

### Candidate audio WebSocket

Client endpoint:

```text
WS /v1/ws/audio/{session_id}
```

Typical control flow:

```text
client                Nora                 STT provider
  |                    |                        |
  | open               |                        |
  |------------------->| start nora.stt.v1     |
  |                    |----------------------->|
  |                    |<---------------- ready |
  | stream_opened      |                        |
  |<-------------------|                        |
  | chunk #0           | binary audio           |
  |------------------->|----------------------->|
  | chunk_ack          |                        |
  |<-------------------|                        |
  |                    |<-------------- partial |
  | transcript_partial |                        |
  |<-------------------|                        |
  |                    |<---------------- final |
  | transcript_final   |                        |
  |<-------------------|                        |
```

The transport keeps ordered sequence numbers, bounded buffering, reconnect tokens, generation checks, and backpressure limits.

### Interviewer audio WebSocket

Client endpoint:

```text
WS /v1/ws/tts/{session_id}
```

The client opens a stream for an existing interviewer turn:

```json
{
  "type": "open",
  "data": {
    "turn_id": "interviewer-turn-id",
    "locale": "en-US",
    "config": {
      "encoding": "pcm16",
      "sample_rate_hz": 24000,
      "channels": 1
    }
  }
}
```

Nora responds with `stream_opened`, then sends each audio chunk as:

1. an `audio_chunk` JSON metadata frame containing sequence + generation;
2. the corresponding binary WebSocket audio frame.

The stream ends with `stream_completed` or `stream_cancelled`.

### Barge-in across STT and TTS

When candidate audio begins while a server-side TTS stream is active:

1. the voice coordinator records the barge-in;
2. the voice generation increments;
3. active TTS state is cancelled;
4. the provider-side TTS session is cancelled;
5. the candidate STT stream proceeds under the new generation.

This prevents stale synthesized audio from remaining authoritative after the candidate has interrupted.

## Generic provider protocols

### nora.stt.v1

After opening the provider WebSocket, Nora sends:

```json
{
  "type": "start",
  "schema": "nora.stt.v1",
  "locale": "ar-SA",
  "audio": {
    "encoding": "pcm16",
    "sample_rate_hz": 16000,
    "channels": 1
  }
}
```

The provider must acknowledge:

```json
{"type": "ready"}
```

Audio then travels as binary frames.

Provider transcript events:

```json
{"type":"partial","text":"...","confidence":0.75}
{"type":"final","text":"...","confidence":0.94}
```

Nora control events include `commit`, `close`, and `cancel`.

### nora.tts.v1

Nora sends:

```json
{
  "type": "start",
  "schema": "nora.tts.v1",
  "text": "Describe a production incident.",
  "locale": "en-US",
  "generation": 3,
  "audio": {
    "encoding": "pcm16",
    "sample_rate_hz": 24000,
    "channels": 1
  }
}
```

The provider acknowledges with `{"type":"ready"}`, streams binary audio frames, then sends `{"type":"done"}`.

Nora can send a generation-scoped `cancel` event on barge-in.

## Configuration

Install the optional voice dependency:

```bash
pip install -e '.[voice]'
```

Streaming STT:

```bash
export NORA_STREAMING_STT_MODE=websocket-json
export NORA_STREAMING_STT_URL=wss://stt.example/v1/stream
export NORA_STREAMING_STT_TOKEN=...
```

Streaming TTS:

```bash
export NORA_STREAMING_TTS_MODE=websocket-json
export NORA_STREAMING_TTS_URL=wss://tts.example/v1/stream
export NORA_STREAMING_TTS_TOKEN=...
export NORA_STREAMING_TTS_VOICE=default
```

Plain `ws://` endpoints are rejected by configuration unless explicitly enabled for trusted local development.
