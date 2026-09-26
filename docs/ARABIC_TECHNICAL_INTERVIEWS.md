# Arabic Technical Interviews

Nora v0.5 carries explicit language metadata from realtime transcripts into candidate turns and VoxRubric exports so Arabic technical interviews can be evaluated without treating Arabic/English code-switching as transcript noise.

## Transcript metadata

A final `TranscriptEvent` can include:

```text
locale
dialect
technical_vocabulary_packs
asr_reference_text
asr_critical_terms
```

Only `text` is required. The other fields are optional and can be supplied by a speech provider, benchmark harness, replay fixture, or controlled evaluation environment.

Nora does not infer a dialect label from nationality or identity. A dialect label is exported only when explicitly supplied.

## Script and code-switch profile

For each final candidate transcript Nora records:

- the effective ASR locale;
- explicit dialect label when present;
- Arabic-character count;
- Latin-character count;
- whether both scripts appear in the transcript;
- configured technical vocabulary packs;
- technical terms detected from those packs.

Code-switch detection is descriptive metadata. It is not a candidate score.

## Built-in technical vocabulary packs

Nora currently ships three Arabic/English packs:

```text
ar-software-engineering-v1
ar-ai-ml-v1
ar-data-engineering-v1
```

They cover common terms used in software engineering, AI/ML, and data-engineering interviews, including English technical tokens and Arabic equivalents.

The packs are intended for transcript-preservation analysis and prompt/provider configuration. They do not define hiring criteria.

## VoxRubric interoperability

Candidate turn metadata flows into the VoxRubric trace.

When a controlled benchmark provides them, Nora preserves the exact keys used by VoxRubric's ASR-preservation evaluation:

```text
asr_reference_text
asr_critical_terms
```

The export also includes:

```text
metadata.language_profiles
metadata.asr_preservation_turn_ids
metadata.code_switch_turn_ids
```

A language-profile entry can contain:

- turn ID;
- locale;
- dialect;
- detected/expected code-switch state;
- vocabulary pack IDs;
- detected technical terms;
- ASR reference text;
- ASR critical terms.

Live production transcripts do not need a reference transcript. Reference text is primarily for benchmark/replay evaluation.

## Benchmark fixtures

The repository includes:

```text
benchmarks/arabic_technical_interviews.json
```

The first pack contains Saudi/Najdi, Egyptian, Gulf, and Arabic-only technical interview examples spanning:

- backend incident response;
- RAG / AI systems;
- data engineering;
- system design.

The fixtures explicitly identify the terms that should survive transcription and whether Arabic/English code-switching is expected.

## Privacy and fairness boundary

Language metadata is about transcript behavior, not candidate quality.

Nora does not use:

- dialect prestige;
- accent;
- nationality;
- inferred ethnicity;
- fluency style

as hiring signals.

The purpose of this metadata is to detect whether the speech/transcription system preserved the technical content the candidate actually expressed.
