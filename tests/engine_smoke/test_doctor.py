import json

import pytest

from scripts.engine_doctor import build_report, main, validate_report


def _health(state="ready"):
    return {
        "state": state,
        "summary": "fixture",
        "checks": [],
        "fingerprint": "fixture-fingerprint",
        "available": state != "blocked",
        "reason": None,
    }


class _Result:
    def __init__(self, state="ready"):
        self._state = state

    def to_dict(self):
        return _health(self._state)


def test_doctor_json_is_schema_validated(monkeypatch, capsys):
    monkeypatch.setattr("scripts.engine_doctor.probe_engine", lambda _preset: _Result())
    exit_code = main(["--json"])
    report = json.loads(capsys.readouterr().out)
    validate_report(report)
    assert report["schema_version"] == 1
    assert exit_code == 0


def test_doctor_returns_nonzero_for_blocked_engine(monkeypatch, capsys):
    monkeypatch.setattr("scripts.engine_doctor.probe_engine", lambda _preset: _Result("blocked"))
    assert main([]) == 1
    assert "[BLOCKED]" in capsys.readouterr().out


def test_heavy_doctor_tiers_require_explicit_opt_in():
    with pytest.raises(ValueError, match="--run-engine-smoke"):
        build_report(["qwen3-asr-1.7b"], tier="load", opted_in=False)
