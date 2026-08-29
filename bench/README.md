# WDER benchmark

The benchmark compares normalized reference words with hypothesis words and scores
Speaker mismatches only on text-aligned words. It finds the best one-to-one mapping
between hypothesis and reference Speaker labels, so engine-local labels do not affect
the result.

Reference words labelled `SHARED_ACCOUNT` are excluded from partial WDER. This is
required for Meet transcripts where Chris and Garrah used the same Google account.
After manual annotation, replace those labels with `CHRIS` or `GARRAH` and rerun the
same manifest to obtain full WDER.

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
the normalized reference excerpt and the current hypothesis excerpt.

The manifest references the original audio and exports. It does not copy the `.mov`.
The reference can be Gemini Markdown or JSON with `segments` or `words` entries. Each
entry needs `text` and `speaker`.

The report includes WDER, aligned-word coverage, shared-account word counts, and the
Speaker mapping selected for the comparison. Coverage matters: a low WDER with low
coverage is not evidence of good attribution.
