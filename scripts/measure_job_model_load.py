"""Measure cold per-process model loading required by the local Job runner plan."""

from __future__ import annotations

import argparse
import time


def _measure(label: str, load) -> None:
    started = time.perf_counter()
    load()
    elapsed = time.perf_counter() - started
    print(f"{label}_seconds={elapsed:.2f}", flush=True)
    print("note=process exit releases model memory", flush=True)


def measure(component: str) -> None:
    from presets import get_preset

    if component in {"parakeet", "faster-whisper"}:
        from engines import make_transcriber
        from run_config import resolve_run_config

        preset_id = (
            "parakeet-tdt-0.6b-v3"
            if component == "parakeet"
            else "faster-whisper-large-v3"
        )
        transcriber = make_transcriber(resolve_run_config(preset_id))
        _measure(f"{component}_adapter_load", transcriber.load)
        if component == "parakeet":
            print(
                "note=parakeet.cpp loads weights inside its existing CLI subprocess "
                "for each transcription; adapter_load_seconds only checks local paths",
                flush=True,
            )
        return

    if component == "pyannote":
        from engines import make_diarizer
        from preferences import hf_token
        from run_config import resolve_run_config

        preset = get_preset("faster-whisper-large-v3")
        diarizer = make_diarizer(
            resolve_run_config(preset["id"]),
            hf_token=hf_token(),
        )
        _measure(
            "pyannote_pipeline_load",
            lambda: diarizer.get_pipeline(diarizer.clustering, diarizer.auth_token),
        )
        return

    if component == "ecapa":
        from services.embedding_service import EmbeddingService

        _measure("ecapa_model_load", EmbeddingService.get_model)
        return

    raise ValueError(f"Unknown component: {component}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "component",
        choices=("parakeet", "faster-whisper", "pyannote", "ecapa"),
    )
    args = parser.parse_args()
    measure(args.component)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
