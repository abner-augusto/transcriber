# 0006 - Isolate Python Engines in Dedicated Runtimes

**Status**: accepted

## Context

Qwen3-ASR and VibeVoice require incompatible, rapidly changing Python ML stacks.
Loading both stacks in the Celery process also permits global Transformers
registrations and native-library state to leak between Jobs.

## Decision

Each Python Engine runs in its own pinned virtual environment. The core process
starts that environment's Python executable with an argument list and exchanges a
schema-versioned request and response through UTF-8 JSON files. Standard output and
standard error are diagnostics only. Pickle and arbitrary Python objects are not
part of the protocol.

Requests carry only absolute local audio/model paths, vocabulary, device choice,
and a bounded set of Engine options. Responses carry validated Words, optional
native Turns, scalar diagnostics, the runtime fingerprint, and a structured error.
Protocol files are deleted after every outcome. Debug retention may keep only the
response and never audio, vocabulary, environment variables, or the request.

The launch uses no shell. Timeout, cancellation, abnormal exit, missing/partial
output, invalid JSON, and incompatible schema versions are primary Engine failures
and therefore fail the Job. Optional capability failures are reported as degraded
diagnostics while valid fallback Words and Turns cross the boundary normally.

Health checks identify the selected dedicated executable and include it in the
runtime fingerprint. Qwen and VibeVoice never share an interpreter.

## Local-only guarantee

The subprocess boundary does not change ADR-0001: Meeting audio, vocabulary,
transcripts, Words, and Turns remain on the machine. Runners must not call hosted
inference services. Once artifacts are installed, execution works offline.

## Adding a Python Engine

Add an immutable runtime manifest and requirement file, a runner that implements
protocol version 1, a thin core adapter, health metadata checks, installer entries,
and all three smoke-test tiers. A protocol-breaking field change requires a schema
version bump and coordinated adapter/runner migration.
