"""Run every Preset over the same audio and see which one you want.

    python bench/compare_engines.py test.mp3
    python bench/compare_engines.py test.mp3 --presets whisper-large-v3-turbo,parakeet-tdt-0.6b-v3

Prints wall time, real-time factor and word count per Preset, and how far the two
transcripts agree. Writes each transcript to bench/out/<preset>.txt so you can read
them side by side — the numbers tell you which Engine is faster, but only your eyes
tell you which one is right.

Transcription only: this does not diarize, so it needs no GPU beyond the Engine's own.
"""

import argparse
import difflib
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import presets as preset_store
from engines import engine_status, make_transcriber

OUT_DIR = Path(__file__).parent / "out"


def to_wav(audio_path: Path) -> Path:
    """Both Engines want 16 kHz mono PCM."""
    wav = OUT_DIR / (audio_path.stem + ".16k.wav")
    if wav.exists():
        return wav
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(audio_path), "-ar", "16000", "-ac", "1", str(wav)],
        capture_output=True,
        check=True,
    )
    return wav


def duration_of(wav: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(wav)],
        capture_output=True,
        text=True,
        check=True,
    )
    return float(out.stdout.strip())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("audio", type=Path)
    parser.add_argument("--presets", help="Comma-separated preset ids (default: all available)")
    parser.add_argument("--vocabulary", default=None, help="Domain terms, if the Engine takes a prompt")
    args = parser.parse_args()

    if not args.audio.exists():
        print(f"No such file: {args.audio}")
        return 1

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    wanted = args.presets.split(",") if args.presets else None
    chosen = []
    for preset in preset_store.list_presets():
        if wanted and preset["id"] not in wanted:
            continue
        status = engine_status(preset)
        if not status["available"]:
            print(f"skipping {preset['id']}: {status['reason']}")
            continue
        chosen.append(preset)

    if not chosen:
        print("No runnable presets.")
        return 1

    wav = to_wav(args.audio)
    audio_seconds = duration_of(wav)
    print(f"\n{args.audio.name} — {audio_seconds:.1f}s of audio\n")

    results = []
    for preset in chosen:
        transcriber = make_transcriber(preset)
        started = time.perf_counter()
        words = transcriber.transcribe(str(wav), vocabulary=args.vocabulary)
        elapsed = time.perf_counter() - started

        text = "".join(w.text for w in words).strip()
        (OUT_DIR / f"{preset['id']}.txt").write_text(text, encoding="utf-8")
        results.append({"preset": preset, "elapsed": elapsed, "words": words, "text": text})

    print(f"{'PRESET':<28} {'ENGINE':<14} {'SECONDS':>8} {'RTF':>7} {'WORDS':>7}")
    print("-" * 70)
    for r in results:
        rtf = audio_seconds / r["elapsed"] if r["elapsed"] else 0
        print(
            f"{r['preset']['id']:<28} {r['preset']['engine']:<14} "
            f"{r['elapsed']:>8.1f} {rtf:>6.1f}x {len(r['words']):>7}"
        )

    if len(results) == 2:
        a, b = results
        ratio = difflib.SequenceMatcher(None, a["text"].split(), b["text"].split()).ratio()
        print(f"\nTranscripts agree on {ratio:.0%} of words.")

    print(f"\nTranscripts written to {OUT_DIR}/ — read them.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
