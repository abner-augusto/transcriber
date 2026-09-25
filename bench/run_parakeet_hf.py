"""Transcribe audio with a Transformers-format Parakeet TDT checkpoint.

Evaluates Parakeet fine-tunes published only as Transformers safetensors, such as
moondream/parakeet-ultra, which parakeet.cpp cannot load. Running the base
nvidia/parakeet-tdt-0.6b-v3 through the same code separates the fine-tune's gain
from the runtime and quantization differences with the parakeet.cpp GGUFs.

The audio is cut where it is quietest, as the parakeet.cpp adapter does, because
the encoder's attention grows quadratically with clip length.

Needs torch, transformers >= 5.16 and librosa (the Parakeet feature extractor
imports it). Usage:

    venv-engines\\parakeet-hf-bench\\Scripts\\python.exe -m bench.run_parakeet_hf meeting.wav \\
        --model moondream/parakeet-ultra --output bench\\out\\parakeet-ultra.json
"""

from __future__ import annotations

import argparse
import json
import subprocess
import time
from pathlib import Path

import numpy as np
import torch
from transformers import AutoProcessor, GenerationConfig, ParakeetForTDT

from engines.chunking import chunk_bounds

SAMPLE_RATE = 16000
CHUNK_SECONDS = 300
MIN_TAIL_SECONDS = 10

# Fine-tunes ship weights and tokenizer.json but no processor or generation config.
# The tokenizer is identical to the base model's, so both come from there.
BASE_MODEL = "nvidia/parakeet-tdt-0.6b-v3"


def load_audio(path: Path) -> np.ndarray:
    result = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-f", "f32le", "-ac", "1", "-ar", str(SAMPLE_RATE), "-"],
        capture_output=True,
        check=True,
    )
    return np.frombuffer(result.stdout, dtype=np.float32)


def tokens_to_words(tokens: list[dict], offset: float) -> list[dict]:
    """Merge subword tokens into Words; a token starting with a space opens a new Word."""
    words: list[dict] = []
    for token in tokens:
        text = token["token"]
        if not text:
            continue
        if words and not text.startswith(" "):
            words[-1]["text"] += text
            words[-1]["end"] = round(token["end"] + offset, 3)
            continue
        words.append(
            {
                "start": round(token["start"] + offset, 3),
                "end": round(token["end"] + offset, 3),
                "text": " " + text.lstrip(),
            }
        )
    return words


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("audio", type=Path)
    parser.add_argument("--model", default="moondream/parakeet-ultra")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--dtype", choices=["float32", "bfloat16", "float16"], default="float32")
    parser.add_argument("--chunk-seconds", type=float, default=CHUNK_SECONDS)
    args = parser.parse_args()

    device = "cuda" if torch.cuda.is_available() else "cpu"
    audio = load_audio(args.audio)
    duration = len(audio) / SAMPLE_RATE

    t0 = time.perf_counter()
    processor = AutoProcessor.from_pretrained(BASE_MODEL)
    generation_config = GenerationConfig.from_pretrained(BASE_MODEL)
    model = ParakeetForTDT.from_pretrained(args.model, dtype=getattr(torch, args.dtype)).to(device).eval()
    load_seconds = time.perf_counter() - t0
    if device == "cuda":
        torch.cuda.reset_peak_memory_stats()

    bounds = chunk_bounds(audio, SAMPLE_RATE, args.chunk_seconds, MIN_TAIL_SECONDS)
    words: list[dict] = []
    t0 = time.perf_counter()
    for index, (start, end) in enumerate(bounds, 1):
        chunk = audio[int(start * SAMPLE_RATE) : int(end * SAMPLE_RATE)]
        inputs = processor(chunk, sampling_rate=SAMPLE_RATE, return_tensors="pt").to(device, model.dtype)
        with torch.no_grad():
            output = model.generate(**inputs, generation_config=generation_config)
        _, timestamps = processor.decode(output.sequences, durations=output.durations, skip_special_tokens=True)
        chunk_words = tokens_to_words(timestamps[0], start)
        words.extend(chunk_words)
        print(f"chunk {index}/{len(bounds)} {start / 60:.1f}-{end / 60:.1f} min: {len(chunk_words)} words", flush=True)
    inference_seconds = time.perf_counter() - t0

    report = {
        "model": args.model,
        "audio": str(args.audio),
        "dtype": args.dtype,
        "duration_seconds": round(duration, 2),
        "load_seconds": round(load_seconds, 2),
        "inference_seconds": round(inference_seconds, 2),
        "realtime_factor": round(duration / inference_seconds, 1),
        "peak_vram_mb": round(torch.cuda.max_memory_allocated() / 2**20) if device == "cuda" else None,
        "chunks": [[round(s, 2), round(e, 2)] for s, e in bounds],
        "words": words,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(
        f"{len(words)} words, {inference_seconds:.1f}s for {duration / 60:.1f} min "
        f"({report['realtime_factor']}x realtime, peak {report['peak_vram_mb']} MB) -> {args.output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
