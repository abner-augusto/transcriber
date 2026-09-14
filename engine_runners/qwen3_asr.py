from engine_runners._main import run


def factory(request):
    from engines.qwen3_asr import Qwen3AsrTranscriber
    return Qwen3AsrTranscriber(model_path=request.model_path, aligner_path=request.aligner_path,
        language=request.options.get("language", "Portuguese"), device=request.device,
        chunk_seconds=float(request.options.get("chunk_seconds", 300)), overlap_seconds=float(request.options.get("overlap_seconds", 30)))


if __name__ == "__main__": raise SystemExit(run("qwen3-asr", factory))
