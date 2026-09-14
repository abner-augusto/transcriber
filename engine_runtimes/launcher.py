"""Safe subprocess launcher for isolated Python Engine runtimes."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Callable

from .protocol import EngineRequest, EngineResponse, ProtocolError, write_json

MAX_DIAGNOSTIC_CHARS = 16_384
PROJECT_ROOT = Path(__file__).resolve().parents[1]


class EngineRuntimeError(RuntimeError):
    pass


def launch_engine(*, python: str, module: str, request: EngineRequest, timeout: float,
                  cancelled: Callable[[], bool] | None = None, debug_directory: str | None = None) -> EngineResponse:
    if timeout <= 0:
        raise ValueError("Engine runtime timeout must be greater than zero")
    executable = Path(python).resolve(strict=True)
    if not executable.is_file():
        raise EngineRuntimeError(f"Engine runtime executable not found: {executable}")
    work = Path(tempfile.mkdtemp(prefix=f"transcriber-{request.engine_id}-"))
    request_path, response_path = work / "request.json", work / "response.json"
    try:
        write_json(request_path, request.to_dict())
        process = subprocess.Popen([str(executable), "-m", module, "--request", str(request_path), "--response", str(response_path)],
                                   shell=False, cwd=str(PROJECT_ROOT), stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
        deadline = time.monotonic() + timeout
        while process.poll() is None:
            if cancelled and cancelled():
                process.kill(); process.communicate()
                raise EngineRuntimeError("Engine runtime cancelled")
            if time.monotonic() >= deadline:
                process.kill(); process.communicate()
                raise EngineRuntimeError(f"Engine runtime timed out after {timeout:g}s")
            time.sleep(0.1)
        stdout, stderr = process.communicate()
        detail = (stderr or stdout or "").strip()[-MAX_DIAGNOSTIC_CHARS:]
        if process.returncode != 0:
            raise EngineRuntimeError(f"Engine runtime exited with code {process.returncode}: {detail}")
        if not response_path.is_file():
            raise EngineRuntimeError("Engine runtime exited without a response")
        try:
            response = EngineResponse.from_dict(json.loads(response_path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError, ProtocolError) as exc:
            raise EngineRuntimeError(f"Engine runtime returned an invalid response: {exc}") from exc
        if response.error:
            raise EngineRuntimeError(f"{response.error['code']}: {response.error['message']}")
        return response
    finally:
        try:
            if debug_directory:
                target = Path(debug_directory).resolve() / work.name
                target.mkdir(parents=True, exist_ok=True)
                if response_path.is_file():
                    shutil.copy2(response_path, target / "response.json")
                # Never retain request.json: it contains the audio path and vocabulary.
        finally:
            shutil.rmtree(work, ignore_errors=True)
