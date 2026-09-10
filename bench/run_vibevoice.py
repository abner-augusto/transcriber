"""Run VibeVoice-ASR-Streaming-7B over audio and measure performance, VRAM and speaker attribution.

Usage:
    venv\\Scripts\\python.exe bench/run_vibevoice.py test.mp3
    venv\\Scripts\\python.exe bench/run_vibevoice.py test.mp3 --context-info "Arquitetura,Sinop"
"""

import argparse
import difflib
import json
import os
import re
import sys
import time
import unicodedata
from pathlib import Path

import torch

# Ensure local packages and transcriber root are discoverable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vibevoice.modular.modeling_vibevoice_asr import VibeVoiceASRForConditionalGeneration
from vibevoice.processor.audio_utils import load_audio_use_ffmpeg
from vibevoice.processor.vibevoice_asr_processor import VibeVoiceASRProcessor

OUT_DIR = Path(__file__).parent / "out"


def normalize_text(text: str) -> str:
    """Normalize text for phonetic/orthographic alignment."""
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def parse_segments_from_transcript(full_text: str) -> list[dict]:
    """Parse raw transcript into speaker segments for WDER evaluation."""
    pattern = re.compile(r"(Speaker\s+\d+):\s*", re.IGNORECASE)
    parts = pattern.split(full_text)
    segments = []
    if not parts:
        return segments

    if parts[0].strip() and not pattern.match(parts[0]):
        segments.append({"speaker": "UNKNOWN", "text": parts[0].strip()})
        parts = parts[1:]
    else:
        parts = parts[1:]

    for i in range(0, len(parts) - 1, 2):
        speaker = parts[i].strip()
        text = parts[i + 1].strip()
        if text:
            segments.append({"speaker": speaker, "text": text})
    return segments


def parse_segment_words(segments: list[dict]) -> list[dict]:
    """Extract word tokens from segments with speaker, raw, norm, span, and segment index."""
    tokens = []
    for seg_idx, seg in enumerate(segments):
        text = seg.get("text", "")
        spk = seg.get("speaker", "UNKNOWN")
        for match in re.finditer(r"[\w]+(?:['’][\w]+)*", text, re.UNICODE):
            tokens.append({
                "word": match.group(),
                "norm": normalize_text(match.group()),
                "speaker": spk,
                "seg_idx": seg_idx,
                "span": match.span(),
            })
    return tokens


def stitch_window(
    prev_segments: list[dict],
    curr_segments: list[dict],
    global_speakers_seen: set[str],
    next_global_id: int,
    overlap_seconds: float = 45.0,
) -> tuple[list[dict], dict[str, str], int]:
    """Stitch current window transcript into global transcript across overlap.
    
    1. Align word sequences in the overlap region using SequenceMatcher.
    2. Map current window local speakers to global speakers via majority vote.
    3. Cut duplicated speech in the overlap region from the current window.
    """
    if not curr_segments:
        return [], {}, 0
    if not prev_segments:
        return curr_segments, {}, 0

    prev_tokens = parse_segment_words(prev_segments)
    curr_tokens = parse_segment_words(curr_segments)

    if not curr_tokens:
        return curr_segments, {}, 0

    # Limit search scope to overlap region (~4 words/sec * overlap_sec * 1.5)
    search_token_count = max(200, int(overlap_seconds * 4 * 1.5))
    search_prev_tokens = prev_tokens[-search_token_count:] if len(prev_tokens) > search_token_count else prev_tokens
    search_curr_tokens = curr_tokens[:search_token_count] if len(curr_tokens) > search_token_count else curr_tokens

    p_words = [t["norm"] for t in search_prev_tokens]
    c_words = [t["norm"] for t in search_curr_tokens]

    matcher = difflib.SequenceMatcher(None, p_words, c_words)
    blocks = matcher.get_matching_blocks()

    votes: dict[str, dict[str, int]] = {}
    cut_point = 0

    for b in blocks:
        if b.size > 0:
            for i in range(b.size):
                p_tok = search_prev_tokens[b.a + i]
                c_tok = search_curr_tokens[b.b + i]
                votes.setdefault(c_tok["speaker"], {})
                votes[c_tok["speaker"]][p_tok["speaker"]] = (
                    votes[c_tok["speaker"]].get(p_tok["speaker"], 0) + 1
                )
            if b.size >= 2 or (b.size == 1 and len(c_words[b.b]) > 3):
                cut_point = max(cut_point, b.b + b.size)

    # Resolve speaker mappings greedily by highest vote count
    candidate_pairs = []
    for c_spk, p_counts in votes.items():
        for p_spk, count in p_counts.items():
            candidate_pairs.append((count, c_spk, p_spk))
    candidate_pairs.sort(reverse=True)

    local_to_global: dict[str, str] = {}
    used_global = set()

    for count, c_spk, p_spk in candidate_pairs:
        if c_spk not in local_to_global and p_spk not in used_global:
            total_for_c = sum(votes[c_spk].values())
            if count / total_for_c >= 0.4:
                local_to_global[c_spk] = p_spk
                used_global.add(p_spk)

    # Assign new unique global IDs to unmapped speakers
    curr_spk_set = list(dict.fromkeys(s["speaker"] for s in curr_segments))
    for c_spk in curr_spk_set:
        if c_spk == "UNKNOWN":
            local_to_global[c_spk] = "UNKNOWN"
        elif c_spk not in local_to_global:
            while f"Speaker {next_global_id}" in global_speakers_seen or f"Speaker {next_global_id}" in used_global:
                next_global_id += 1
            new_name = f"Speaker {next_global_id}"
            local_to_global[c_spk] = new_name
            used_global.add(new_name)
            next_global_id += 1

    # Extract new segments after cut point
    new_segments = []
    if cut_point >= len(curr_tokens):
        # Everything was matched in previous window
        pass
    elif cut_point == 0:
        for s in curr_segments:
            new_segments.append({
                "speaker": local_to_global.get(s["speaker"], s["speaker"]),
                "text": s["text"],
            })
    else:
        target_tok = curr_tokens[cut_point]
        target_seg_idx = target_tok["seg_idx"]
        target_char_start = target_tok["span"][0]

        for seg_idx, s in enumerate(curr_segments):
            if seg_idx < target_seg_idx:
                continue
            elif seg_idx == target_seg_idx:
                rem = s["text"][target_char_start:].strip().lstrip(",;: ")
                if rem:
                    new_segments.append({
                        "speaker": local_to_global.get(s["speaker"], s["speaker"]),
                        "text": rem,
                    })
            else:
                new_segments.append({
                    "speaker": local_to_global.get(s["speaker"], s["speaker"]),
                    "text": s["text"],
                })

    return new_segments, local_to_global, cut_point


def load_frame_config(model_path: str) -> dict:
    name = "preprocessor_config.json"
    if os.path.isdir(model_path):
        config_path = os.path.join(model_path, name)
    else:
        from huggingface_hub import hf_hub_download

        config_path = hf_hub_download(model_path, name)

    with open(config_path, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    sample_rate = cfg.get("target_sample_rate", 24000)
    frame_seconds = cfg.get("speech_tok_compress_ratio", 3200) / sample_rate
    chunk_frames = cfg.get("chunk_frames", 15)
    lookahead_frames = cfg.get("lookahead_frames", 4)
    return {
        "sample_rate": sample_rate,
        "chunk_duration": chunk_frames * frame_seconds,
        "text_audio_delay": lookahead_frames * frame_seconds,
    }


def get_vram_mb() -> float:
    if torch.cuda.is_available():
        return torch.cuda.memory_allocated() / (1024 * 1024)
    return 0.0


def get_vram_reserved_mb() -> float:
    if torch.cuda.is_available():
        return torch.cuda.memory_reserved() / (1024 * 1024)
    return 0.0


def main():
    parser = argparse.ArgumentParser(description="VibeVoice ASR Streaming 7B Benchmark")
    parser.add_argument("audio", type=Path, help="Path to audio file (mp3, wav, mov, etc.)")
    parser.add_argument(
        "--model-path",
        type=str,
        default=r"C:\Users\abner\_repos\_local-ai\models\VibeVoice-ASR-Streaming-7B",
        help="Path or HF ID for VibeVoice model",
    )
    parser.add_argument(
        "--context-info",
        type=str,
        default=None,
        help="Vocabulary / hotwords to bias recognition (e.g. 'Abner,Garrah,Sinop')",
    )
    parser.add_argument(
        "--device",
        type=str,
        default="cuda" if torch.cuda.is_available() else "cpu",
        help="Device to run inference on",
    )
    parser.add_argument(
        "--attn-implementation",
        type=str,
        default="sdpa",
        choices=["flash_attention_2", "sdpa", "eager"],
        help="Attention implementation",
    )
    parser.add_argument(
        "--max-new-tokens",
        type=int,
        default=256,
        help="Max tokens per chunk",
    )
    parser.add_argument(
        "--quantize",
        type=str,
        default="4bit",
        choices=["4bit", "8bit", "none"],
        help="Quantization method (4bit, 8bit, none)",
    )
    parser.add_argument(
        "--out-prefix",
        type=str,
        default="vibevoice-7b",
        help="Output filename prefix in bench/out/",
    )
    parser.add_argument(
        "--max-duration",
        type=float,
        default=None,
        help="Maximum audio duration in seconds to process (default: all)",
    )
    parser.add_argument(
        "--window-seconds",
        type=float,
        default=None,
        help="Window duration in seconds for streaming inference (e.g. 600.0)",
    )
    parser.add_argument(
        "--overlap-seconds",
        type=float,
        default=45.0,
        help="Overlap duration in seconds between consecutive windows (e.g. 45.0)",
    )
    args = parser.parse_args()

    if not args.audio.exists():
        print(f"Audio file not found: {args.audio}")
        return 1

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print("=" * 70)
    print("VibeVoice-ASR-Streaming-7B Benchmark")
    print("=" * 70)
    print(f"Audio file:   {args.audio}")
    print(f"Model path:   {args.model_path}")
    print(f"Device:       {args.device}")
    print(f"Quantization: {args.quantize}")
    if args.context_info:
        print(f"Hotwords:     {args.context_info}")

    # 1. Config & Processor
    print("\n[1/4] Reading model configuration...")
    frame_config = load_frame_config(args.model_path)
    sample_rate = frame_config["sample_rate"]
    chunk_dur = frame_config["chunk_duration"]
    delay = frame_config["text_audio_delay"]
    print(f"  Sample rate: {sample_rate} Hz | Chunk: {chunk_dur:.3f}s | Delay: {delay:.3f}s")

    processor = VibeVoiceASRProcessor.from_pretrained(args.model_path)

    # 2. Model Loading
    print("\n[2/4] Loading model weights into VRAM...")
    load_start = time.perf_counter()
    model_dtype = torch.bfloat16 if args.device == "cuda" else torch.float32

    if args.quantize == "4bit" and args.device == "cuda":
        from transformers import BitsAndBytesConfig

        q_config = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_compute_dtype=torch.bfloat16,
            bnb_4bit_quant_type="nf4",
        )
        model = VibeVoiceASRForConditionalGeneration.from_pretrained(
            args.model_path,
            quantization_config=q_config,
            device_map=args.device,
            attn_implementation=args.attn_implementation,
        ).eval()
    elif args.quantize == "8bit" and args.device == "cuda":
        from transformers import BitsAndBytesConfig

        q_config = BitsAndBytesConfig(load_in_8bit=True)
        model = VibeVoiceASRForConditionalGeneration.from_pretrained(
            args.model_path,
            quantization_config=q_config,
            device_map=args.device,
            attn_implementation=args.attn_implementation,
        ).eval()
    else:
        model = VibeVoiceASRForConditionalGeneration.from_pretrained(
            args.model_path,
            dtype=model_dtype,
            attn_implementation=args.attn_implementation,
        ).to(args.device).eval()
    load_elapsed = time.perf_counter() - load_start

    vram_loaded = get_vram_mb()
    print(f"  Model loaded in {load_elapsed:.2f}s")
    print(f"  VRAM allocated: {vram_loaded:.1f} MB (reserved: {get_vram_reserved_mb():.1f} MB)")

    # 3. Audio Loading
    print("\n[3/4] Loading audio via ffmpeg...")
    audio, _ = load_audio_use_ffmpeg(str(args.audio), resample=True, target_sr=sample_rate)
    total_audio_duration = len(audio) / sample_rate
    if args.max_duration is not None and args.max_duration > 0:
        max_samples = int(args.max_duration * sample_rate)
        audio = audio[:max_samples]
        print(f"  Audio sliced to {len(audio)/sample_rate:.2f}s (file total: {total_audio_duration:.2f}s)")
    duration = len(audio) / sample_rate
    print(f"  Audio duration to process: {duration:.2f}s ({len(audio)} samples)")

    # Compute window intervals
    if args.window_seconds and args.window_seconds > 0 and duration > args.window_seconds:
        window_samples = int(args.window_seconds * sample_rate)
        overlap_samples = int(args.overlap_seconds * sample_rate)
        step_samples = window_samples - overlap_samples

        windows = []
        start_sample = 0
        while start_sample < len(audio):
            end_sample = min(start_sample + window_samples, len(audio))
            windows.append((start_sample, end_sample))
            if end_sample == len(audio):
                break
            start_sample += step_samples
    else:
        windows = [(0, len(audio))]

    print(f"  Execution mode: {'Windowed (' + str(len(windows)) + ' windows, overlap=' + str(args.overlap_seconds) + 's)' if len(windows) > 1 else 'Single window'}")

    # Output file paths
    out_txt = OUT_DIR / f"{args.out_prefix}.txt"
    out_json = OUT_DIR / f"{args.out_prefix}.json"

    # 4. Streaming Inference
    print("\n[4/4] Running streaming inference...")
    total_gen_start = time.perf_counter()
    all_segments = []
    global_speakers_seen = set()
    next_global_speaker_id = 0
    all_chunks = []
    window_stats = []
    peak_vram_mb = get_vram_mb()
    peak_reserved_mb = get_vram_reserved_mb()

    for win_idx, (w_start, w_end) in enumerate(windows):
        w_start_sec = w_start / sample_rate
        w_end_sec = w_end / sample_rate
        w_dur_sec = w_end_sec - w_start_sec
        win_label = f"Window {win_idx + 1}/{len(windows)}" if len(windows) > 1 else "Full Audio"
        print(f"\n--- [{win_label}] {w_start_sec:.1f}s - {w_end_sec:.1f}s ({w_dur_sec:.1f}s) ---")

        audio_slice = audio[w_start:w_end]
        audio_tensor = torch.from_numpy(audio_slice)

        torch.cuda.empty_cache()
        win_gen_start = time.perf_counter()
        win_chunks = []

        for chunk_idx, total_chunks, chunk_text in model.streaming_generate(
            audio_tensor=audio_tensor,
            tokenizer=processor.tokenizer,
            chunk_duration=chunk_dur,
            text_audio_delay=delay,
            sample_rate=sample_rate,
            max_new_tokens_per_chunk=args.max_new_tokens,
            temperature=0.0,
            context_info=args.context_info,
        ):
            win_chunks.append(chunk_text)
            current_time = time.perf_counter() - total_gen_start
            cur_vram = get_vram_mb()
            cur_res = get_vram_reserved_mb()
            peak_vram_mb = max(peak_vram_mb, cur_vram)
            peak_reserved_mb = max(peak_reserved_mb, cur_res)
            all_chunks.append({
                "window": win_idx + 1,
                "chunk": chunk_idx + 1,
                "total": total_chunks,
                "text": chunk_text,
                "elapsed_total": round(current_time, 3),
                "vram_mb": round(cur_vram, 1),
            })
            if chunk_text.strip():
                if (chunk_idx + 1) % 10 == 0 or (chunk_idx + 1) == total_chunks:
                    print(f"  [W{win_idx+1} {chunk_idx + 1:3d}/{total_chunks:3d}] (VRAM: {cur_vram:.0f}MB / Res: {cur_res:.0f}MB) {chunk_text.strip()}", flush=True)
                else:
                    print(f"  [W{win_idx+1} {chunk_idx + 1:3d}/{total_chunks:3d}] {chunk_text.strip()}", flush=True)

        win_elapsed = time.perf_counter() - win_gen_start
        win_rtf = w_dur_sec / win_elapsed if win_elapsed > 0 else 0
        win_full_text = "".join(win_chunks).strip()
        win_raw_segments = parse_segments_from_transcript(win_full_text)

        del audio_tensor
        torch.cuda.empty_cache()

        if win_idx == 0:
            all_segments = win_raw_segments
            for s in all_segments:
                global_speakers_seen.add(s["speaker"])
                m = re.match(r"Speaker\s+(\d+)", s["speaker"], re.IGNORECASE)
                if m:
                    next_global_speaker_id = max(next_global_speaker_id, int(m.group(1)) + 1)
            print(f"  Window 1 baseline established: {len(all_segments)} segments, speakers: {sorted(global_speakers_seen)}")
        else:
            stitched_new_segs, mapping, cut_pt = stitch_window(
                prev_segments=all_segments,
                curr_segments=win_raw_segments,
                global_speakers_seen=global_speakers_seen,
                next_global_id=next_global_speaker_id,
                overlap_seconds=args.overlap_seconds,
            )
            print(f"  Window {win_idx + 1} stitched: {len(stitched_new_segs)} new segments appended.")
            print(f"  Speaker mapping: {mapping}")
            print(f"  Cut point token: {cut_pt}")

            for s in stitched_new_segs:
                global_speakers_seen.add(s["speaker"])
                m = re.match(r"Speaker\s+(\d+)", s["speaker"], re.IGNORECASE)
                if m:
                    next_global_speaker_id = max(next_global_speaker_id, int(m.group(1)) + 1)

            all_segments.extend(stitched_new_segs)

        window_stats.append({
            "window": win_idx + 1,
            "start_sec": round(w_start_sec, 2),
            "end_sec": round(w_end_sec, 2),
            "duration_sec": round(w_dur_sec, 2),
            "elapsed_sec": round(win_elapsed, 2),
            "rtf": round(win_rtf, 2),
            "peak_vram_mb": round(cur_vram, 1),
            "segments_count": len(all_segments),
        })

        # Save progressive transcript and metrics after each window
        full_transcript = "\n".join(f"  {s['speaker']}: {s['text']}" for s in all_segments)
        out_txt.write_text(full_transcript, encoding="utf-8")

        total_elapsed = time.perf_counter() - total_gen_start
        overall_rtf = w_end_sec / total_elapsed if total_elapsed > 0 else 0

        metrics = {
            "audio": str(args.audio),
            "duration_sec": round(duration, 2),
            "processed_duration_sec": round(w_end_sec, 2),
            "generation_sec": round(total_elapsed, 2),
            "load_sec": round(load_elapsed, 2),
            "rtf": round(overall_rtf, 2),
            "vram_allocated_mb": round(get_vram_mb(), 1),
            "vram_reserved_mb": round(get_vram_reserved_mb(), 1),
            "peak_vram_allocated_mb": round(peak_vram_mb, 1),
            "peak_vram_reserved_mb": round(peak_reserved_mb, 1),
            "windows": window_stats,
            "chunks": all_chunks,
            "segments": all_segments,
            "full_transcript": full_transcript,
        }
        out_json.write_text(json.dumps(metrics, indent=2, ensure_ascii=False), encoding="utf-8")

    total_elapsed = time.perf_counter() - total_gen_start
    final_rtf = duration / total_elapsed if total_elapsed > 0 else 0

    print("\n" + "=" * 70)
    print("Benchmark Results Summary")
    print("=" * 70)
    print(f"Audio Duration:   {duration:.2f}s")
    print(f"Inference Time:   {total_elapsed:.2f}s")
    print(f"Speedup / RTF:    {final_rtf:.2f}x real-time")
    print(f"Peak VRAM:        {peak_vram_mb:.1f} MB (Allocated), {peak_reserved_mb:.1f} MB (Reserved)")
    print(f"Total Segments:   {len(all_segments)}")
    print(f"Global Speakers:  {sorted(global_speakers_seen)}")
    print(f"Saved transcript: {out_txt}")
    print(f"Saved metrics:    {out_json}")
    print("=" * 70)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
