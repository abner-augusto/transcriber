# WDER benchmark

## Vocabulary Correction benchmark

After editing Segments on the local Meetings you want to evaluate, run:

```powershell
.\.venv\Scripts\python.exe -m bench.vocabulary_correction
```

The script compares each edited Segment with Segments re-derived from the
Meeting's stored Words, once without Vocabulary Correction and once with the
Meeting's current Vocabulary and Misheard Forms. The Misheard Forms stored in
the database are not used: they were learned from these same edits. Instead the
script learns them again from the edits of the *other* Meetings
(leave-one-out), so no Meeting is credited for a form it taught. It aligns Segments by
their start and end times (within 1.5 seconds), then reports corrected user
changes (**hits**), corrections the user did not make (**false changes**), and
user changes still left wrong (**misses**). Counts are tokens, totaled per
Meeting and across the report.

The default JSON report is written to `bench/out/vocabulary_correction.json`.
To choose another local output path, pass `--output path\to\report.json`.
The table and JSON contain only Meeting IDs, Engine names, and counts; they do
not include transcript text, Meeting titles, Vocabulary, or correction forms.
Keep the report local because Meeting IDs and Engine usage are still local
Meeting metadata.

The benchmark compares normalized reference words with hypothesis words and scores
Speaker mismatches only on text-aligned words. It finds the best one-to-one mapping
between hypothesis and reference Speaker labels, so engine-local labels do not affect
the result.

Reference words labelled `SHARED_ACCOUNT` are excluded from partial WDER. This is
required for Meet transcripts where Chris and Garrah used the same Google account.
After manual annotation, replace those labels with `CHRIS` or `GARRAH` and apply the
queue to obtain full WDER.

Run a sample with:

```text
venv\Scripts\python.exe -m bench.wder bench\samples\2026-08-18-arquitetura-03\manifest.json
```

Generate a manual review queue for the shared account with:

```text
venv\Scripts\python.exe -m bench.wder bench\samples\2026-08-18-arquitetura-03\manifest-parakeet-rerun.json --review-queue review.json
```

Listen to each queued interval in the original audio and replace `resolved_speaker`
with `CHRIS` or `GARRAH`. The queue is grouped by hypothesis segment and keeps both
the normalized reference excerpt and the current hypothesis excerpt. Then score the
annotated queue with:

```text
venv\Scripts\python.exe -m bench.wder bench\samples\2026-08-18-arquitetura-03\manifest-parakeet-rerun.json --apply-review-queue review.json
```

Generate a timestamped report of aligned speaker mismatches with:

```text
venv\Scripts\python.exe -m bench.wder bench\samples\2026-08-18-arquitetura-03\manifest-parakeet-rerun-reviewed.json --error-report errors.json
```

The manifest references the original audio and exports. It does not copy the `.mov`.
The reference can be Gemini Markdown or JSON with `segments` or `words` entries. Each
entry needs `text` and `speaker`. A meeting-specific `reference_speaker_overrides` map
can record manual corrections without changing the global speaker map.

The report includes WDER, aligned-word coverage, shared-account word counts, and the
Speaker mapping selected for the comparison. Coverage matters: a low WDER with low
coverage is not evidence of good attribution.
