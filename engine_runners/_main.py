import argparse
import hashlib
import json
import sys
import traceback
from pathlib import Path

from engine_runtimes.manifest import load_manifest, runtime_for_engine
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
        if request.operation == "load":
            adapter.load()
            transcription = None
        elif request.operation == "diarize":
            turns = adapter.diarize(request.audio_path)
            transcription = None
        else:
            transcription = adapter.transcribe(request.audio_path, vocabulary=request.vocabulary)
        words = () if transcription is None else tuple(transcription.words)
        native = None if transcription is None else transcription.native
        turns = tuple(turns) if request.operation == "diarize" else (None if native is None else tuple(native.turns))
        manifest = load_manifest(runtime_for_engine(engine_id))
        fingerprint = hashlib.sha256((manifest.runtime_id + "\n" + sys.executable + "\n" + sys.version).encode()).hexdigest()
        provenance = {} if transcription is None else transcription.provenance
        response = EngineResponse(tuple(words), turns, provenance, fingerprint)
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
