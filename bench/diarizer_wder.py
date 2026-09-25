"""WDER of one Diarizer's Turns, with the Words held fixed.

Builds a Meeting's diarization the way the Diarization stage does, derives Segments
from fixed Words with ``derive_segments``, and scores them with ``bench.wder``. Only
the Turns change between runs, so a WDER difference belongs to the Diarizer.

- Single-track: ``--audio``; the Turns are bounded to VAD speech, as
  ``tasks.diarization.bound_to_speech`` does.
- Dual-track: ``--mic`` and ``--system``; the host is every VAD region of the mic
  track and the Turns (of the system track) are bounded to its VAD, as
  ``tasks.diarization._diarize_dual_track`` does.

Turns come from ``--turns`` (a JSON written by ``bench.run_nemotron_diarization``,
or by ``--save-turns`` here) or ``--pyannote``, which runs the app's Diarizer. Turns
without exclusive ones get them computed from their overlaps. Usage:

    .venv\\Scripts\\python.exe -m bench.diarizer_wder --words words.json --reference ref_gemini.md \\
        --audio meeting.wav --pyannote --save-turns pyannote-turns.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from bench.wder import _apply_reference_speaker_overrides, evaluate, load_json_transcript, load_reference
from engines import DiarizationResult, Turn, Word
from services.vad_service import VadService
from tasks.diarization import bound_to_speech
from tasks.dual_track import HOST_SPEAKER, build_dual_diarization, compute_exclusive_turns, host_turns_from_vad
from transcript.diarization import MeetingDiarization
from transcript.segments import derive_segments


def load_turns(path: Path) -> DiarizationResult:
    data = json.loads(path.read_text(encoding="utf-8"))
    turns = [Turn.from_dict(t) for t in data["turns"]]
    exclusive = data.get("exclusive_turns")
    return DiarizationResult(
        turns=turns,
        exclusive_turns=[Turn.from_dict(t) for t in exclusive] if exclusive else compute_exclusive_turns(turns),
    )


def run_pyannote(audio: Path) -> DiarizationResult:
    from engines.pyannote import PyannoteDiarizer
    from preferences import hf_token

    result = PyannoteDiarizer(auth_token=hf_token()).diarize(str(audio))
    return result if isinstance(result, DiarizationResult) else DiarizationResult(turns=list(result))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--words", type=Path, required=True, help="JSON with a 'words' list")
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument(
        "--override", action="append", default=[], metavar="FROM=TO",
        help="reference speaker override, e.g. SHARED_ACCOUNT=GARRAH",
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--turns", type=Path)
    source.add_argument("--pyannote", action="store_true")
    parser.add_argument("--save-turns", type=Path, help="write the Diarizer's Turns before VAD bounding")
    parser.add_argument("--audio", type=Path, help="single-track audio")
    parser.add_argument("--mic", type=Path, help="dual-track mic audio")
    parser.add_argument("--system", type=Path, help="dual-track system audio")
    parser.add_argument("--output", type=Path, help="write the derived Segments")
    args = parser.parse_args()
    if bool(args.audio) == bool(args.mic and args.system):
        parser.error("give either --audio or both --mic and --system")

    diarized_audio = args.audio or args.system
    result = load_turns(args.turns) if args.turns else run_pyannote(diarized_audio)
    if args.save_turns:
        args.save_turns.write_text(json.dumps({
            "engine": "pyannote" if args.pyannote else str(args.turns),
            "turns": [t.to_dict() for t in result.turns],
            "exclusive_turns": [t.to_dict() for t in result.exclusive_turns] if result.exclusive_turns else None,
        }, indent=1), encoding="utf-8")

    vad = VadService()
    if args.audio:
        diarization = bound_to_speech(result, str(args.audio), vad, engine="bench")
    else:
        host_turns = host_turns_from_vad(vad.compute_vad_segments(str(args.mic)))
        remote_turns = vad.mask_turns_to_vad(result.turns, vad.compute_vad_segments(str(args.system)))
        merged = build_dual_diarization(host_turns, remote_turns)
        diarization = MeetingDiarization(
            engine="bench", turns=merged.turns, exclusive_turns=merged.exclusive_turns,
            overlaps=merged.overlaps, host_label=HOST_SPEAKER,
        )

    words = [Word.from_dict(w) for w in json.loads(args.words.read_text(encoding="utf-8"))["words"]]
    segments = derive_segments(words, diarization)
    output = args.output or Path(args.words).with_suffix(".segments.json")
    output.write_text(json.dumps({"segments": segments}, ensure_ascii=False, indent=1), encoding="utf-8")

    overrides = dict(item.split("=", 1) for item in args.override)
    reference = _apply_reference_speaker_overrides(load_reference(args.reference), overrides)
    evaluation = evaluate(reference, load_json_transcript(output))
    print(
        f"speakers {len(diarization.speaker_labels)}  WDER {evaluation.wder:.2%}  "
        f"coverage {evaluation.coverage:.2%}  errors {evaluation.speaker_errors}/"
        f"{evaluation.aligned_evaluable_words}  mapping {evaluation.speaker_mapping}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
