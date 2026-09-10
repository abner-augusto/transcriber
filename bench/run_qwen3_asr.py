"""Run Qwen3-ASR-1.7B over audio with sliding windows and measure performance, VRAM, and vocabulary accuracy.

Usage:
    venv\\Scripts\\python.exe bench/run_qwen3_asr.py test.mp3
    venv\\Scripts\\python.exe bench/run_qwen3_asr.py path/to/meeting.mov --language Portuguese --context "Abner, Camilla, Chris, Ricardo, Garrah, Sinop, Brasil Urbano, Arquitetura"
"""

import argparse
import difflib
import json
import os
import re
import subprocess
import sys
import time
import unicodedata
from pathlib import Path

import numpy as np
import torch
from transformers import AutoModelForMultimodalLM, AutoProcessor

OUT_DIR = Path(__file__).parent / "out"


def normalize_text(text: str) -> str:
    """Normalize text for phonetic/orthographic alignment."""
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    cleaned = "".join(c for c in decomposed if not unicodedata.combining(c))
    return re.sub(r"[^\w\s]", "", cleaned).strip()


def get_vram_mb() -> float:
    if torch.cuda.is_available():
        return torch.cuda.memory_allocated() / (1024 * 1024)
    return 0.0


def get_vram_reserved_mb() -> float:
    if torch.cuda.is_available():
        return torch.cuda.memory_reserved() / (1024 * 1024)
    return 0.0


def load_audio_ffmpeg(audio_path: Path, start_sec: float = 0.0, duration_sec: float | None = None) -> np.ndarray:
    """Load audio via ffmpeg stream into a 16kHz float32 mono numpy array."""
    cmd = ["ffmpeg", "-v", "error"]
    if start_sec > 0:
        cmd.extend(["-ss", str(start_sec)])
    if duration_sec is not None and duration_sec > 0:
        cmd.extend(["-t", str(duration_sec)])
    cmd.extend([
        "-i", str(audio_path),
        "-f", "f32le",
        "-ar", "16000",
        "-ac", "1",
        "-"
    ])
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    out, err = proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"FFmpeg decoding failed: {err.decode('utf-8', errors='replace')}")
    return np.frombuffer(out, dtype=np.float32)


def get_audio_duration(audio_path: Path) -> float:
    """Get exact audio duration in seconds via ffprobe."""
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "csv=p=0",
        str(audio_path),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    val = res.stdout.strip()
    return float(val) if val else 0.0


def stitch_text(prev_text: str, curr_text: str, search_tokens: int = 150) -> tuple[str, int]:
    """Stitch current text window into previous text, discarding duplicated overlap words."""
    prev_words = prev_text.split()
    curr_words = curr_text.split()
    if not prev_words:
        return curr_text, 0
    if not curr_words:
        return prev_text, 0

    p_slice = prev_words[-search_tokens:] if len(prev_words) > search_tokens else prev_words
    c_slice = curr_words[:search_tokens] if len(curr_words) > search_tokens else curr_words

    p_norm = [normalize_text(w) for w in p_slice]
    c_norm = [normalize_text(w) for w in c_slice]

    matcher = difflib.SequenceMatcher(None, p_norm, c_norm)
    blocks = matcher.get_matching_blocks()

    cut_point = 0
    for b in blocks:
        if b.size >= 2:
            end_curr = b.b + b.size
            if end_curr > cut_point:
                cut_point = end_curr

    if cut_point > 0:
        remaining_curr = curr_words[cut_point:]
        return prev_text + " " + " ".join(remaining_curr), cut_point
    else:
        return prev_text + " " + curr_text, 0


def main():
    parser = argparse.ArgumentParser(description="Qwen3-ASR-1.7B Benchmark with Sliding Windows")
    parser.add_argument("audio", type=Path, help="Path to audio file (mp3, wav, mov, etc.)")
    parser.add_argument(
        "--model-path",
        type=str,
        default=r"C:\Users\abner\_repos\_local-ai\models\Qwen3-ASR-1.7B-hf",
        help="Path or HF ID for Qwen3-ASR model",
    )
    parser.add_argument(
        "--language",
        type=str,
        default="Portuguese",
        help="Target language (e.g. 'Portuguese', 'English') or None for auto detection",
    )
    parser.add_argument(
        "--context",
        type=str,
        default="Abner, Camilla, Chris, Ricardo, Garrah, Sinop, Brasil Urbano, Arquitetura, cisterna, gradil, pergolado",
        help="Hotwords / domain vocabulary prompt",
    )
    parser.add_argument(
        "--device",
        type=str,
        default="cuda" if torch.cuda.is_available() else "cpu",
        help="Device to run inference on",
    )
    parser.add_argument(
        "--window-sec",
        type=float,
        default=300.0,
        help="Sliding window duration in seconds (default 300s = 5 min)",
    )
    parser.add_argument(
        "--overlap-sec",
        type=float,
        default=30.0,
        help="Sliding window overlap in seconds (default 30s)",
    )
    parser.add_argument(
        "--max-new-tokens",
        type=int,
        default=4096,
        help="Max new tokens per window generation",
    )
    parser.add_argument(
        "--out-prefix",
        type=str,
        default="qwen3-asr-1.7b",
        help="Output filename prefix in bench/out/",
    )
    args = parser.parse_args()

    if not args.audio.exists():
        print(f"Error: Audio file not found: {args.audio}", flush=True)
        return 1

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print("=" * 70, flush=True)
    print("Qwen3-ASR-1.7B Benchmark Runner", flush=True)
    print("=" * 70, flush=True)
    print(f"Audio file:   {args.audio}", flush=True)
    print(f"Model path:   {args.model_path}", flush=True)
    print(f"Device:       {args.device}", flush=True)
    print(f"Language:     {args.language}", flush=True)
    print(f"Context:      {args.context}", flush=True)
    print(f"Window:       {args.window_sec}s (overlap: {args.overlap_sec}s)", flush=True)

    # 1. Inspect Audio Duration
    total_duration = get_audio_duration(args.audio)
    print(f"Total audio duration: {total_duration:.2f}s ({total_duration/60:.2f} min)", flush=True)

    # 2. Load Model & Processor
    print("\n[1/3] Loading Qwen3-ASR model and processor...", flush=True)
    t_load_start = time.perf_counter()
    processor = AutoProcessor.from_pretrained(args.model_path)
    model_dtype = torch.bfloat16 if "cuda" in args.device else torch.float32
    model = AutoModelForMultimodalLM.from_pretrained(
        args.model_path,
        dtype=model_dtype,
        device_map=args.device,
    )
    t_load_elapsed = time.perf_counter() - t_load_start
    print(f"  Model loaded in {t_load_elapsed:.2f}s", flush=True)
    print(f"  VRAM allocated: {get_vram_mb():.1f} MB (reserved: {get_vram_reserved_mb():.1f} MB)", flush=True)

    # 3. Process Windows
    print("\n[2/3] Transcribing audio with sliding window...", flush=True)
    windows = []
    if total_duration <= args.window_sec:
        windows.append((0.0, total_duration))
    else:
        step = args.window_sec - args.overlap_sec
        start = 0.0
        while start < total_duration:
            dur = min(args.window_sec, total_duration - start)
            windows.append((start, dur))
            if start + dur >= total_duration:
                break
            start += step

    print(f"Total windows to process: {len(windows)}", flush=True)

    stitched_transcript = ""
    window_metrics = []
    total_inference_time = 0.0
    peak_vram = get_vram_mb()

    for idx, (w_start, w_dur) in enumerate(windows):
        w_end = w_start + w_dur
        print(f"\n--- Window {idx + 1}/{len(windows)} [{w_start:.1f}s - {w_end:.1f}s ({w_dur:.1f}s)] ---", flush=True)

        t_w_start = time.perf_counter()
        w_audio = load_audio_ffmpeg(args.audio, start_sec=w_start, duration_sec=w_dur)

        inputs = processor.apply_transcription_request(
            audio=w_audio,
            language=args.language,
            prompt=args.context,
        ).to(model.device, model.dtype)

        with torch.no_grad():
            output_ids = model.generate(**inputs, max_new_tokens=args.max_new_tokens)

        gen_ids = output_ids[:, inputs["input_ids"].shape[1]:]
        w_text = processor.decode(gen_ids[0], return_format="transcription_only").strip()
        t_w_elapsed = time.perf_counter() - t_w_start
        total_inference_time += t_w_elapsed

        w_words = len(w_text.split())
        w_rtf = w_dur / t_w_elapsed if t_w_elapsed > 0 else 0
        cur_vram = get_vram_mb()
        peak_vram = max(peak_vram, cur_vram)

        print(f"  Generated {w_words} words in {t_w_elapsed:.2f}s ({w_rtf:.2f}x RTF, VRAM: {cur_vram:.1f} MB)", flush=True)

        # Stitch
        stitched_transcript, cut_words = stitch_text(stitched_transcript, w_text)
        if cut_words > 0:
            print(f"  [Stitcher] Overlap matched: cut {cut_words} duplicate words from window start.", flush=True)

        window_metrics.append({
            "window_index": idx + 1,
            "start_sec": round(w_start, 2),
            "duration_sec": round(w_dur, 2),
            "elapsed_sec": round(t_w_elapsed, 2),
            "rtf": round(w_rtf, 2),
            "word_count": w_words,
            "cut_duplicate_words": cut_words,
            "raw_text": w_text,
        })

    # 4. Final Output & Metrics
    print("\n[3/3] Saving outputs and calculating metrics...", flush=True)
    out_txt = OUT_DIR / f"{args.out_prefix}.txt"
    out_json = OUT_DIR / f"{args.out_prefix}.json"

    out_txt.write_text(stitched_transcript, encoding="utf-8")
    overall_rtf = total_duration / total_inference_time if total_inference_time > 0 else 0
    total_words = len(stitched_transcript.split())

    final_report = {
        "audio": str(args.audio),
        "total_duration_sec": round(total_duration, 2),
        "total_inference_sec": round(total_inference_time, 2),
        "model_load_sec": round(t_load_elapsed, 2),
        "overall_rtf": round(overall_rtf, 2),
        "peak_vram_allocated_mb": round(peak_vram, 1),
        "peak_vram_reserved_mb": round(get_vram_reserved_mb(), 1),
        "language": args.language,
        "context_prompt": args.context,
        "total_word_count": total_words,
        "num_windows": len(windows),
        "window_metrics": window_metrics,
        "transcript": stitched_transcript,
    }
    out_json.write_text(json.dumps(final_report, indent=2, ensure_ascii=False), encoding="utf-8")

    print("\n" + "=" * 70, flush=True)
    print("Qwen3-ASR Benchmark Completed Successfully!", flush=True)
    print("=" * 70, flush=True)
    print(f"Total Duration:     {total_duration:.2f}s ({total_duration/60:.2f} min)", flush=True)
    print(f"Total Inference:    {total_inference_time:.2f}s ({total_inference_time/60:.2f} min)", flush=True)
    print(f"Overall Speedup:    {overall_rtf:.2f}x real-time", flush=True)
    print(f"Total Words:        {total_words}", flush=True)
    print(f"Peak VRAM:          {peak_vram:.1f} MB (Allocated), {get_vram_reserved_mb():.1f} MB (Reserved)", flush=True)
    print(f"Saved Text:         {out_txt}", flush=True)
    print(f"Saved JSON:         {out_json}", flush=True)
    print("=" * 70, flush=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
