"""Diarize audio with NVIDIA Nemotron 3 Diarization and write its Turns as JSON.

The model is a Sortformer: it labels up to eight speakers per 10 ms frame, in order of
first arrival. Offline mode runs the whole recording through one forward, which walks
it in 340-frame chunks with a speaker cache, so a long Meeting needs no chunking here.

Needs a Transformers build that has ``nemotron3_diarization`` (5.18.0.dev0 at the
time of writing, installed from a pinned main commit). Usage:

    venv-engines\\nemotron-diar-bench\\Scripts\\python.exe -m bench.run_nemotron_diarization \\
        meeting.wav --output bench\\out\\nemotron-turns.json

Score the Turns with ``bench.diarizer_wder``.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import time
from pathlib import Path

import numpy as np
import torch
from transformers import AutoModelForAudioFrameClassification, AutoProcessor

MODEL_ID = "nvidia/Nemotron-3-Diarization"
SAMPLE_RATE = 16000


def load_audio(path: Path) -> np.ndarray:
    result = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-f", "f32le", "-ac", "1", "-ar", str(SAMPLE_RATE), "-"],
        capture_output=True,
        check=True,
    )
    return np.frombuffer(result.stdout, dtype=np.float32)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("audio", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--threshold", type=float, default=0.5, help="speaker probability that counts as speech")
    args = parser.parse_args()

    device = "cuda" if torch.cuda.is_available() else "cpu"
    audio = load_audio(args.audio)
    duration = len(audio) / SAMPLE_RATE

    t0 = time.perf_counter()
    processor = AutoProcessor.from_pretrained(MODEL_ID)
    model = AutoModelForAudioFrameClassification.from_pretrained(MODEL_ID).to(device).eval()
    load_seconds = time.perf_counter() - t0
    if device == "cuda":
        torch.cuda.reset_peak_memory_stats()

    t0 = time.perf_counter()
    inputs = processor(audio, sampling_rate=SAMPLE_RATE).to(device, dtype=model.dtype)
    with torch.inference_mode():
        logits = model(**inputs).logits
    segments = processor.extract_speaker_dict(logits, inputs.attention_mask, threshold=args.threshold)[0]
    inference_seconds = time.perf_counter() - t0

    turns = [
        {"start": s["Start"], "end": s["End"], "speaker": f"SPEAKER_{s['Speaker']:02d}"}
        for s in segments
        if s["End"] > s["Start"]
    ]
    report = {
        "engine": MODEL_ID,
        "audio": str(args.audio),
        "threshold": args.threshold,
        "duration_seconds": round(duration, 2),
        "load_seconds": round(load_seconds, 2),
        "inference_seconds": round(inference_seconds, 2),
        "realtime_factor": round(duration / inference_seconds, 1),
        "peak_vram_mb": round(torch.cuda.max_memory_allocated() / 2**20) if device == "cuda" else None,
        "speakers": sorted({t["speaker"] for t in turns}),
        "turns": turns,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(
        f"{len(turns)} Turns, {len(report['speakers'])} speakers, {inference_seconds:.1f}s for "
        f"{duration / 60:.1f} min ({report['realtime_factor']}x realtime, peak {report['peak_vram_mb']} MB)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
