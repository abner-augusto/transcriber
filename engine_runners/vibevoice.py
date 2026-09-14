from engine_runners._main import run


def factory(request):
    from engines.vibevoice import VibeVoiceTranscriber
    return VibeVoiceTranscriber(model_path=request.model_path, aligner_path=request.aligner_path,
        device=request.device, window_seconds=float(request.options.get("window_seconds", 600)),
        overlap_seconds=float(request.options.get("overlap_seconds", 45)))


if __name__ == "__main__": raise SystemExit(run("vibevoice", factory))
