import ast
import json
from pathlib import Path

import pytest

from engine_runtimes.launcher import EngineRuntimeError, launch_engine
from engine_runtimes.protocol import EngineRequest


def _request(tmp_path):
    audio = tmp_path / "áudio com espaço.wav"; audio.touch()
    model = tmp_path / "modelo ç"; model.mkdir(exist_ok=True)
    return EngineRequest("transcribe", "qwen3-asr", str(audio.resolve()), "Garrah", str(model.resolve()), None, "cpu", {})


def _response(error=None):
    return {"schema_version": 1, "words": [], "native_diarization": None,
            "diagnostics": {}, "runtime_fingerprint": "fingerprint", "error": error}


class FakeProcess:
    def __init__(self, *, polls=None, returncode=0, stdout="", stderr=""):
        self.polls, self.returncode = iter((returncode,) if polls is None else polls), returncode
        self.stdout, self.stderr, self.killed, self.communicated = stdout, stderr, False, False

    def poll(self):
        try: return next(self.polls)
        except StopIteration: return self.returncode

    def communicate(self):
        self.communicated = True
        return self.stdout, self.stderr

    def kill(self): self.killed = True; self.returncode = -9


def _install_fake(monkeypatch, tmp_path, process, response=_response()):
    runtime = tmp_path / "Runtime Ω" / "python.exe"; runtime.parent.mkdir(exist_ok=True); runtime.touch()
    work = tmp_path / "protocol work"; work.mkdir()
    captured = {}

    def popen(argv, **kwargs):
        captured.update(argv=argv, kwargs=kwargs)
        if response is not None:
            Path(argv[-1]).write_text(response if isinstance(response, str) else json.dumps(response), encoding="utf-8")
        return process

    monkeypatch.setattr("engine_runtimes.launcher.tempfile.mkdtemp", lambda **kwargs: str(work))
    monkeypatch.setattr("engine_runtimes.launcher.subprocess.Popen", popen)
    return runtime, work, captured


def test_success_uses_argv_shell_false_and_unicode_paths(monkeypatch, tmp_path):
    process = FakeProcess(); runtime, work, captured = _install_fake(monkeypatch, tmp_path, process)
    result = launch_engine(python=str(runtime), module="engine_runners.qwen3_asr", request=_request(tmp_path), timeout=5)
    assert result.runtime_fingerprint == "fingerprint"
    assert isinstance(captured["argv"], list) and captured["argv"][0] == str(runtime.resolve())
    assert captured["kwargs"]["shell"] is False and "protocol work" in captured["argv"][-1]
    assert Path(captured["kwargs"]["cwd"]) == Path(__file__).resolve().parents[1]
    assert not work.exists()


@pytest.mark.parametrize("cancelled,clock,message", [
    (lambda: True, lambda: 0.0, "cancelled"),
    (None, iter((0.0, 10.0)).__next__, "timed out"),
])
def test_timeout_and_cancellation_kill_communicate_and_cleanup(monkeypatch, tmp_path, cancelled, clock, message):
    process = FakeProcess(polls=(None, None)); runtime, work, _ = _install_fake(monkeypatch, tmp_path, process, None)
    monkeypatch.setattr("engine_runtimes.launcher.time.monotonic", clock)
    monkeypatch.setattr("engine_runtimes.launcher.time.sleep", lambda _: None)
    with pytest.raises(EngineRuntimeError, match=message):
        launch_engine(python=str(runtime), module="runner", request=_request(tmp_path), timeout=1, cancelled=cancelled)
    assert process.killed and process.communicated and not work.exists()


@pytest.mark.parametrize("process,response,message", [
    (FakeProcess(returncode=7, stderr="boom"), None, "exited with code 7"),
    (FakeProcess(), None, "without a response"),
    (FakeProcess(), "{broken", "invalid response"),
    (FakeProcess(), _response({"code": "failed", "message": "bad", "retryable": False, "degraded_capabilities": []}), "failed: bad"),
])
def test_crash_missing_invalid_and_structured_error(monkeypatch, tmp_path, process, response, message):
    runtime, work, _ = _install_fake(monkeypatch, tmp_path, process, response)
    with pytest.raises(EngineRuntimeError, match=message):
        launch_engine(python=str(runtime), module="runner", request=_request(tmp_path), timeout=5)
    assert not work.exists()


def test_debug_retains_only_response_and_cleanup_survives_copy_failure(monkeypatch, tmp_path):
    process = FakeProcess(); runtime, work, _ = _install_fake(monkeypatch, tmp_path, process)
    debug = tmp_path / "debug"
    launch_engine(python=str(runtime), module="runner", request=_request(tmp_path), timeout=5, debug_directory=str(debug))
    retained = list(debug.rglob("*"))
    assert any(path.name == "response.json" for path in retained)
    assert all(path.name != "request.json" for path in retained) and not work.exists()

    process = FakeProcess(); runtime, work, _ = _install_fake(monkeypatch, tmp_path, process)
    monkeypatch.setattr("engine_runtimes.launcher.shutil.copy2", lambda *args: (_ for _ in ()).throw(OSError("disk")))
    with pytest.raises(OSError, match="disk"):
        launch_engine(python=str(runtime), module="runner", request=_request(tmp_path), timeout=5, debug_directory=str(debug))
    assert not work.exists()


def test_timeout_must_be_positive(tmp_path):
    with pytest.raises(ValueError, match="greater than zero"):
        launch_engine(python=str(tmp_path / "missing.exe"), module="runner", request=_request(tmp_path), timeout=0)


def test_core_api_and_celery_do_not_import_heavy_python_engines():
    root = Path(__file__).resolve().parents[1]
    targets = [root / "engines" / "__init__.py", root / "engines" / "isolated_python.py",
               *sorted((root / "tasks").glob("*.py")), *sorted((root / "api").glob("*.py"))]
    forbidden = {"engines.qwen3_asr", "engines.vibevoice", "qwen_asr", "vibevoice"}
    violations = []
    for path in targets:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import): names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom): names = [node.module or ""]
            else: continue
            violations.extend(f"{path.name}:{name}" for name in names if any(name == item or name.startswith(item + ".") for item in forbidden))
    assert violations == []
