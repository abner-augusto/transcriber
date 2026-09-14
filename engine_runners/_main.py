import argparse
import hashlib
import json
import sys
import traceback
from pathlib import Path

from engine_runtimes.manifest import load_manifest
from engine_runtimes.protocol import EngineRequest, EngineResponse, read_json, write_json


def run(engine_id, factory):
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", required=True); parser.add_argument("--response", required=True)
    args = parser.parse_args()
    try:
        request = EngineRequest.from_dict(read_json(args.request))
        if request.engine_id != engine_id:
            raise ValueError(f"runner {engine_id} cannot execute {request.engine_id}")
        adapter = factory(request)
        words = adapter.transcribe(request.audio_path, vocabulary=request.vocabulary)
        native = adapter.get_native_diarization() if getattr(adapter, "has_native_diarization", False) else None
        turns = None if native is None else tuple(native.turns)
        manifest = load_manifest(engine_id)
        fingerprint = hashlib.sha256((manifest.runtime_id + "\n" + sys.executable + "\n" + sys.version).encode()).hexdigest()
        degraded = getattr(adapter, "_aligner_unavailable_reason", None)
        response = EngineResponse(tuple(words), turns, {"alignment_degraded": bool(degraded), "alignment_reason": degraded}, fingerprint)
        write_json(args.response, response.to_dict())
        return 0
    except Exception as exc:
        # Primary errors are both structured for inspection and nonzero for truthful Job failure.
        fingerprint = hashlib.sha256((engine_id + "\n" + sys.executable + "\n" + sys.version).encode()).hexdigest()
        response = EngineResponse((), None, {"exception_type": type(exc).__name__}, fingerprint,
            {"code": "engine_execution_failed", "message": str(exc), "retryable": False, "degraded_capabilities": []})
        try: write_json(args.response, response.to_dict())
        finally: traceback.print_exc(file=sys.stderr)
        return 1
