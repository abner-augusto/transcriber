# 06 - Make Vocabulary Useful for Parakeet

**Source:** found during the 2026-09-24 architecture review; see ADR-0007.

**What to build:** A way for the user's Vocabulary to improve parakeet.cpp
output, since `engines/parakeet_cpp.py` ignores it today ("Parakeet takes no
prompt").

**Why:** parakeet.cpp is the Engine used most (ADR-0007) because it already
gets names and technical terms right more often than the others. The
Vocabulary the user supplies currently reaches faster-whisper, whisper.cpp,
qwen3-asr, and vibevoice only, so the Engine the user trusts most gets none of
it.

**Blocked by:** None — can start immediately.

**Status:** needs-exploration

**Options to evaluate:**
- **Engine-agnostic post-correction**: after transcription, fuzzy-match Words
  (normalized, accent-insensitive, phonetic for PT-BR) against Vocabulary
  terms and replace confident near-misses. Works for every Engine; must keep
  Word timings and join-ready spacing (`engines/ports.py::Word`).
- **Decoder-level biasing** in parakeet.cpp (word boosting / context
  biasing for TDT/CTC), if upstream supports it or a patch is feasible.
- **Learned corrections**: reuse the user's past Segment edits as the source
  of replacements (CONTEXT.md: Vocabulary is "supplied by the user or learned
  from their corrections").

**Acceptance criteria (draft):**
- [ ] A `bench/` comparison on the user's own recordings, with and without the chosen approach, for parakeet.cpp and faster-whisper large-v3
- [ ] No regression in WDER (`bench/wder.py`)
- [ ] The Transcriber port docstring and ADR-0007 are updated to match
