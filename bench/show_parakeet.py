import json
import re
import unicodedata
from pathlib import Path

def normalize_text(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    cleaned = "".join(c for c in decomposed if not unicodedata.combining(c))
    return re.sub(r"[^\w\s]", "", cleaned)

# 1. Load Parakeet segments
parakeet_json = Path(r"D:/Nextcloud/_INTEGRARTE.ARQ/2-IAR_PROJETOS/1-ARQUITETURA/_2026/0-VIABILIDADES BRASIL URBANO/1-SINOP - BRASIL URBANO/05-BRIEFINGS/2026-08-18 Reuniao Arquitetura 03 (pre legal).json")
p_data = json.loads(parakeet_json.read_text(encoding="utf-8"))

print("=== PARAKEET SEGMENTS (0 to 180s) ===")
for s in p_data["segments"]:
    if s["end"] <= 185:
        print(f"{s['start']:6.1f} - {s['end']:6.1f} [{s['speaker']}]: {s['text']}")

# 3. Gemini reference
print("\n=== GEMINI GROUND TRUTH (first 25 lines of transcript) ===")
gemini_path = Path(r"D:/Nextcloud/_INTEGRARTE.ARQ/2-IAR_PROJETOS/1-ARQUITETURA/_2026/0-VIABILIDADES BRASIL URBANO/1-SINOP - BRASIL URBANO/05-BRIEFINGS/2026-08-18 Reuniao Arquitetura 03 (pre legal)_gemini.md")
gem_lines = gemini_path.read_text(encoding="utf-8").splitlines()
in_transcript = False
count = 0
for line in gem_lines:
    if "Transcri" in line:
        in_transcript = True
        continue
    if in_transcript and line.strip():
        print(line)
        count += 1
        if count > 20:
            break

