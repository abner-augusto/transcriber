import difflib
import re
import subprocess
import time
import unicodedata
from pathlib import Path
import numpy as np
import torch
from transformers import AutoProcessor, AutoModelForMultimodalLM

def normalize_text(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    cleaned = "".join(c for c in decomposed if not unicodedata.combining(c))
    return re.sub(r"[^\w\s]", "", cleaned).strip()

def load_audio_ffmpeg(audio_path: str, start_sec: float, duration_sec: float) -> np.ndarray:
    cmd = [
        "ffmpeg", "-v", "error",
        "-ss", str(start_sec),
        "-t", str(duration_sec),
        "-i", audio_path,
        "-f", "f32le",
        "-ar", "16000",
        "-ac", "1",
        "-"
    ]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    out, _ = proc.communicate()
    return np.frombuffer(out, dtype=np.float32)

def stitch_text(prev_text: str, curr_text: str, search_tokens: int = 150) -> str:
    prev_words = prev_text.split()
    curr_words = curr_text.split()
    if not prev_words:
        return curr_text
    if not curr_words:
        return prev_text

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
        offset_in_curr = (len(curr_words) - len(c_slice)) if len(curr_words) <= search_tokens else 0
        actual_cut = cut_point
        remaining_curr = curr_words[actual_cut:]
        print(f"  [Stitcher] Matched overlap! Cutting first {actual_cut} words from next window.")
        return prev_text + " " + " ".join(remaining_curr)
    else:
        print("  [Stitcher] No overlap match found, concatenating.")
        return prev_text + " " + curr_text

def main():
    model_id = r"C:\Users\abner\_repos\_local-ai\models\Qwen3-ASR-1.7B-hf"
    audio_path = r"D:/Nextcloud/_INTEGRARTE.ARQ/2-IAR_PROJETOS/1-ARQUITETURA/_2026/0-VIABILIDADES BRASIL URBANO/1-SINOP - BRASIL URBANO/05-BRIEFINGS/2026-08-18 Reuniao Arquitetura 03 (pre legal).mov"
    hotwords = "Abner, Camilla, Chris, Ricardo, Garrah, Sinop, Brasil Urbano, Arquitetura, cisterna, gradil, pergolado"

    print("Loading processor & model...")
    processor = AutoProcessor.from_pretrained(model_id)
    model = AutoModelForMultimodalLM.from_pretrained(model_id, dtype=torch.bfloat16, device_map="cuda")

    # Chunk 1: 0 - 300s
    print("\n--- Window 1 (0 to 300s) ---")
    w1_audio = load_audio_ffmpeg(audio_path, 0, 300)
    inputs = processor.apply_transcription_request(audio=w1_audio, language="Portuguese", prompt=hotwords).to(model.device, model.dtype)
    t0 = time.perf_counter()
    with torch.no_grad():
        out1 = model.generate(**inputs, max_new_tokens=4096)
    gen_ids1 = out1[:, inputs["input_ids"].shape[1]:]
    text1 = processor.decode(gen_ids1[0], return_format="transcription_only")
    t1 = time.perf_counter()
    print(f"Window 1 generated in {t1-t0:.2f}s ({len(w1_audio)/16000/(t1-t0):.2f}x RTF). Words: {len(text1.split())}")
    print("Tail of Window 1:", " ".join(text1.split()[-30:]))

    # Chunk 2: 270 - 570s (30s overlap)
    print("\n--- Window 2 (270 to 570s) ---")
    w2_audio = load_audio_ffmpeg(audio_path, 270, 300)
    inputs2 = processor.apply_transcription_request(audio=w2_audio, language="Portuguese", prompt=hotwords).to(model.device, model.dtype)
    t0 = time.perf_counter()
    with torch.no_grad():
        out2 = model.generate(**inputs2, max_new_tokens=4096)
    gen_ids2 = out2[:, inputs2["input_ids"].shape[1]:]
    text2 = processor.decode(gen_ids2[0], return_format="transcription_only")
    t1 = time.perf_counter()
    print(f"Window 2 generated in {t1-t0:.2f}s ({len(w2_audio)/16000/(t1-t0):.2f}x RTF). Words: {len(text2.split())}")
    print("Head of Window 2:", " ".join(text2.split()[:30]))

    stitched = stitch_text(text1, text2)
    print(f"\nTotal stitched words: {len(stitched.split())}")

if __name__ == "__main__":
    main()
