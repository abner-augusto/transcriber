"""Compare Portuguese vocabulary, technical terminology, and hallucinations across ASR models.

Models compared:
- Gemini Reference (Google Meet live caption reference)
- Parakeet-TDT 0.6B v3 (NeMo / Sherpa)
- VibeVoice-ASR-Streaming-7B (MS / VibeVoice)
- Qwen3-ASR-1.7B (Qwen / Alibaba)
"""

import json
import re
import unicodedata
from pathlib import Path

OUT_DIR = Path(__file__).parent / "out"


def normalize_text(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    cleaned = "".join(c for c in decomposed if not unicodedata.combining(c))
    return re.sub(r"[^\w\s]", " ", cleaned)


def extract_words(text: str) -> list[str]:
    norm = normalize_text(text)
    return [w for w in norm.split() if w]


def main():
    print("=" * 75)
    print("Comprehensive ASR Vocabulary & Transcription Quality Comparison")
    print("Meeting: 2026-08-18 Reuniao Arquitetura 03 (pre legal)")
    print("=" * 75)

    # 1. Load Gemini Reference
    gemini_file = Path(r"D:/Nextcloud/_INTEGRARTE.ARQ/2-IAR_PROJETOS/1-ARQUITETURA/_2026/0-VIABILIDADES BRASIL URBANO/1-SINOP - BRASIL URBANO/05-BRIEFINGS/2026-08-18 Reuniao Arquitetura 03 (pre legal)_gemini.md")
    gemini_lines = gemini_file.read_text(encoding="utf-8").splitlines()
    gemini_text_lines = []
    in_trans = False
    for l in gemini_lines:
        if "Transcri" in l:
            in_trans = True
            continue
        if in_trans and ":" in l:
            _, text = l.split(":", 1)
            gemini_text_lines.append(text.strip())
    gemini_full_text = " ".join(gemini_text_lines)

    # 2. Load Parakeet
    parakeet_file = Path(r"D:/Nextcloud/_INTEGRARTE.ARQ/2-IAR_PROJETOS/1-ARQUITETURA/_2026/0-VIABILIDADES BRASIL URBANO/1-SINOP - BRASIL URBANO/05-BRIEFINGS/2026-08-18 Reuniao Arquitetura 03 (pre legal).json")
    p_data = json.loads(parakeet_file.read_text(encoding="utf-8"))
    parakeet_full_text = " ".join(s["text"] for s in p_data["segments"])

    # 3. Load VibeVoice
    vibevoice_file = OUT_DIR / "vibevoice-7b-reuniao-stitched.txt"
    vv_raw = vibevoice_file.read_text(encoding="utf-8")
    vv_lines = []
    for l in vv_raw.splitlines():
        if ":" in l:
            _, text = l.split(":", 1)
            # Filter out [Silence], [Beep]
            text = re.sub(r"\[(Silence|Beep)\]", "", text).strip()
            if text:
                vv_lines.append(text)
    vibevoice_full_text = " ".join(vv_lines)

    # 4. Load Qwen3-ASR
    qwen3_file = OUT_DIR / "qwen3-asr-1.7b-reuniao.txt"
    qwen3_json = OUT_DIR / "qwen3-asr-1.7b-reuniao.json"
    if not qwen3_file.exists():
        print(f"Warning: {qwen3_file} does not exist yet. Task might still be running.")
        return 1
    qwen3_full_text = qwen3_file.read_text(encoding="utf-8")
    qwen3_meta = json.loads(qwen3_json.read_text(encoding="utf-8")) if qwen3_json.exists() else {}

    # Basic Counts
    g_words = extract_words(gemini_full_text)
    p_words = extract_words(parakeet_full_text)
    v_words = extract_words(vibevoice_full_text)
    q_words = extract_words(qwen3_full_text)

    print("\n--- Model Corpus Overview ---")
    print(f"Gemini Reference:   {len(g_words):5d} words")
    print(f"Parakeet 0.6B:      {len(p_words):5d} words")
    print(f"VibeVoice 7B:       {len(v_words):5d} words")
    print(f"Qwen3-ASR 1.7B:     {len(q_words):5d} words")

    # Domain Terminology Analysis
    domain_terms = [
        "cisterna", "gradil", "pergolado", "permeavel", "garagem",
        "brinquedoteca", "recuo", "sondagem", "gourmet", "piscina",
        "churrasqueira", "insolação", "portaria", "guarita", "lixeira",
        "hall", "elevador", "pilotis", "pavimento", "afastamento",
        "prefeitura", "quadra", "subsolo", "esquadria", "alvenaria",
        "Sinop", "Garrah", "Camilla", "Ricardo", "Abner"
    ]

    print("\n--- Domain & Architectural Terminology Occurrences ---")
    header = f"{'Term':16s} | {'Gemini':6s} | {'Parakeet':8s} | {'VibeVoice':9s} | {'Qwen3-ASR':9s}"
    print(header)
    print("-" * len(header))

    def count_term(term: str, raw_text: str) -> int:
        norm_t = normalize_text(term).strip()
        pattern = re.compile(rf"\b{re.escape(norm_t)}\b", re.IGNORECASE)
        return len(pattern.findall(normalize_text(raw_text)))

    for term in domain_terms:
        c_g = count_term(term, gemini_full_text)
        c_p = count_term(term, parakeet_full_text)
        c_v = count_term(term, vibevoice_full_text)
        c_q = count_term(term, qwen3_full_text)
        print(f"{term:16s} | {c_g:6d} | {c_p:8d} | {c_v:9d} | {c_q:9d}")

    # Hallucinated English Words
    en_words = [
        "the", "you", "what", "that", "view", "repoom", "yes", "tell",
        "with", "is", "it", "we", "have", "not", "this"
    ]

    print("\n--- Hallucinated English Words Frequency ---")
    en_header = f"{'English Word':14s} | {'Parakeet':8s} | {'VibeVoice':9s} | {'Qwen3-ASR':9s}"
    print(en_header)
    print("-" * len(en_header))

    tot_p, tot_v, tot_q = 0, 0, 0
    for w in en_words:
        cp = count_term(w, parakeet_full_text)
        cv = count_term(w, vibevoice_full_text)
        cq = count_term(w, qwen3_full_text)
        tot_p += cp
        tot_v += cv
        tot_q += cq
        print(f"{w:14s} | {cp:8d} | {cv:9d} | {cq:9d}")
    print("-" * len(en_header))
    print(f"{'TOTAL EN ARTIFACTS':14s} | {tot_p:8d} | {tot_v:9d} | {tot_q:9d}")

    # Performance comparison
    print("\n--- Performance & VRAM Summary ---")
    print("Model            | Model Size | Real-Time Factor (RTF) | VRAM Usage | Speaker Diarization")
    print("-" * 80)
    print("Parakeet-TDT     | 0.6B       | ~3.5x - 4.5x           | ~1.8 GB    | No (needs PyAnnote)")
    print("VibeVoice-ASR    | 7.0B       | 1.90x                  | 6.94 GB    | Yes (Native 99.44%)")
    rtf_q = qwen3_meta.get("overall_rtf", 0)
    vram_q = qwen3_meta.get("peak_vram_allocated_mb", 0)
    print(f"Qwen3-ASR        | 1.7B       | {rtf_q:.2f}x                  | {vram_q:.0f} MB     | No (Pure ASR)")
    print("=" * 75)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
