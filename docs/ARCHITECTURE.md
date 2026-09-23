# Architecture

Nora is split into four replaceable planes:

```text
Browser / mobile client
        |
        | WebSocket events
        v
+---------------------+
| Interview transport |
+----------+----------+
           |
           v
+---------------------+       +----------------------+
| Session orchestrator|<----->| InterviewBrain       |
| state + turn graph  |       | hosted/local LLM    |
+----------+----------+       +----------------------+
           |
     +-----+-----+
     |           |
     v           v
   STT adapter  TTS adapter
     |           |
     +-----+-----+
           |
           v
      audio provider

Every completed/partial session
           |
           v
    VoxRubric trace export
```

## Hard boundaries

- Transport never contains hiring logic.
- The brain does not own persistence.
- STT/TTS adapters do not decide scores.
- Candidate-facing interaction and post-interview evaluation are separate pipelines.
- Every follow-up can reference its parent candidate turn.
- Every evaluation should ultimately cite transcript evidence.

## Production replacements

The in-memory store is for development only. A production deployment should replace it with durable storage and encrypt candidate data at rest. Audio retention should be separately configurable from transcript retention.
