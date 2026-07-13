# The LLM feature set is removed, pending a redesign

**Status**: accepted

The inherited codebase used an LLM for four things: naming Speakers by reading the introductions,
extracting insights, running user-defined actions over a transcript, and generating formal minutes.
All four are removed. **This is a rejection of the implementation, not of the idea.** The features
were unreliable in practice and the integration does not reflect how one would build this today.

## Why

- **Unstructured output.** The LLM was asked for JSON in a prose prompt and the reply was parsed by
  hand — including stripping Markdown code fences the model kept adding. No schema, no validation,
  no structured-output or tool-calling support. A malformed reply failed the Job.
- **No reliability layer.** A bare HTTP POST with no retry, no backoff, and no timeout policy. Each
  caller handled failure differently; some swallowed it, some failed the whole Job.
- **Speaker naming was the wrong tool for the job.** It guessed names from regex-matched
  introductions (in Swedish, from the original author's locale) and got them wrong often enough to
  be useless. Voice Profile matching already does this reliably, from the voice rather than from
  what the voice happens to say.
- **It pulled Meeting transcripts off the machine.** Which ADR-0001 now forbids outright.

## What a reintroduction must satisfy

Do not restore the deleted code. A future LLM feature must:

1. Run locally (ADR-0001).
2. Use structured output with a validated schema — never hand-parsed prose.
3. Fail as a degraded result, never as a failed Job. LLM output is an enrichment, not a stage of
   the pipeline.
4. Not duplicate what Voice Profile matching already does well.

## Consequences

- The **Speaker Namer** keeps an unfilled slot for an intro-reading namer. Today it has two working
  implementations — Voice Profile matching and the "Participant N" fallback — which is what makes it
  a real seam rather than a speculative one. That slot is the designated re-entry point if the idea
  is revisited.
- `services/llm_service.py`, the insights / actions / protocol features, and their Presets, tables,
  and UI panels are deleted. Git history is the archive.
- A future architecture review should not read this as "LLMs are out of scope." They are out of
  scope *in this shape*.
