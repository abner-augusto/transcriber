# Long audio is chunked inside the parakeet adapter

**Status**: accepted

parakeet.cpp cannot transcribe a long recording in one piece. Its offline path builds a single
compute graph over the whole clip, and the encoder's attention makes that graph grow with the
**square** of the clip's length. A 15-minute Meeting asks CUDA for 31.9 GB and dies.

The adapter therefore cuts long audio into chunks itself, transcribes each one, and shifts the
Words back onto the Meeting's timeline. A Transcriber still takes an audio file and returns Words
for the whole of it; chunking is the adapter's private business and does not reach the port.

## What was measured

On an RTX 5070 Ti (16,302 MiB) with `tdt-0.6b-v3-q4_k`, peak GPU memory against clip length:

| clip length | peak VRAM |
| --- | --- |
| 5 min | 5,440 MiB |
| 8 min | 10,894 MiB |
| 12 min | 15,588 MiB (barely fits) |
| 15 min | wants 31,855 MiB — out of memory |

`CHUNK_SECONDS = 300` comes from this table: five minutes leaves room for a smaller card and for
pyannote afterwards. Raising it buys little, because the curve is quadratic — the ceiling is closer
than it looks.

**These numbers belong to this model, not to parakeet.cpp.** A new Parakeet release can change the
curve completely. Re-measure before trusting the constant: transcribe slices of increasing length
while polling `nvidia-smi --query-gpu=memory.used`.

## Why not the alternatives

- **`parakeet-cli --stream`** is bounded in memory and would be the natural answer, but it requires a
  cache-aware streaming model and refuses `--json`. It cannot produce word timestamps, and Words are
  the Transcriber's whole output. If a future streaming model learns `--json`, this ADR is worth
  revisiting — it would delete all of the chunking code.
- **Chunking in `tasks/process_meeting.py`** would push an Engine's private limitation into the
  pipeline. whisper.cpp windows internally and has no VRAM ceiling to chunk around — but it turned
  out to need chunking for a different reason; see ADR-0004. A limit that belongs to one Engine is
  handled in that Engine's adapter either way, which is why `chunk_bounds` lives in a shared
  `engines/chunking.py` rather than in the pipeline.
- **Cutting on a fixed clock** loses a word at every boundary: a word sliced down the middle is
  recognised by neither chunk. Cuts snap instead to the quietest half-second within ±15s of the
  boundary, so they land in a pause.

## Consequences

- A chunk boundary is still a small risk to the word that straddles it. Cutting in a pause makes that
  rare, not impossible.
- Trailing silence is the quietest thing in a file, so the last cut snaps hard against the end of the
  audio. A tail shorter than `MIN_TAIL_SECONDS` rides along with the chunk before it rather than
  becoming a chunk of its own.
- The Words of a Meeting are no longer produced by a single parakeet-cli run, so a per-chunk failure
  fails the Job. This is deliberate: a partial transcript is worse than a failed one.
