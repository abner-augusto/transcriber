"""Strict, local-only JSON protocol shared by Engine adapters and runners."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from engines.ports import Turn, Word

SCHEMA_VERSION = 1
_REQUEST_FIELDS = {"schema_version", "operation", "engine_id", "audio_path", "vocabulary", "model_path", "aligner_path", "device", "options"}
_RESPONSE_FIELDS = {"schema_version", "words", "native_diarization", "diagnostics", "runtime_fingerprint", "error"}
_ERROR_FIELDS = {"code", "message", "retryable", "degraded_capabilities"}
_OPTION_FIELDS = {"language", "chunk_seconds", "window_seconds", "overlap_seconds", "quantization"}


class ProtocolError(ValueError):
    pass


def _object(value: Any, where: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise ProtocolError(f"{where} must be an object")
    return value


def _fields(value: Mapping[str, Any], allowed: set[str], required: set[str], where: str) -> None:
    missing, unknown = required - value.keys(), value.keys() - allowed
    if missing:
        raise ProtocolError(f"{where} missing fields: {', '.join(sorted(missing))}")
    if unknown:
        raise ProtocolError(f"{where} unknown fields: {', '.join(sorted(unknown))}")


def _path(value: Any, where: str, *, optional: bool = False) -> str | None:
    if optional and value is None:
        return None
    if not isinstance(value, str) or not value or "\x00" in value:
        raise ProtocolError(f"{where} must be a non-empty local path")
    path = Path(value)
    if not path.is_absolute():
        raise ProtocolError(f"{where} must be absolute")
    return str(path)


def _finite(value: Any, where: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise ProtocolError(f"{where} must be finite")
    return float(value)


@dataclass(frozen=True)
class EngineRequest:
    operation: str
    engine_id: str
    audio_path: str
    vocabulary: str | None
    model_path: str
    aligner_path: str | None
    device: str
    options: Mapping[str, str | float | int | bool]

    def to_dict(self) -> dict[str, Any]:
        return {"schema_version": SCHEMA_VERSION, **self.__dict__}

    @classmethod
    def from_dict(cls, raw: Any) -> "EngineRequest":
        data = _object(raw, "request")
        _fields(data, _REQUEST_FIELDS, _REQUEST_FIELDS - {"operation"}, "request")
        if data["schema_version"] != SCHEMA_VERSION:
            raise ProtocolError(f"unsupported schema_version {data['schema_version']!r}")
        if data["engine_id"] not in {"qwen3-asr", "vibevoice"}:
            raise ProtocolError("request.engine_id is unsupported")
        operation = data.get("operation", "transcribe")
        if operation not in {"load", "transcribe"}:
            raise ProtocolError("request.operation is unsupported")
        options = _object(data["options"], "request.options")
        _fields(options, _OPTION_FIELDS, set(), "request.options")
        for key, value in options.items():
            if isinstance(value, (dict, list)) or value is None:
                raise ProtocolError(f"request.options.{key} must be scalar")
            if isinstance(value, float):
                _finite(value, f"request.options.{key}")
        vocabulary = data["vocabulary"]
        if vocabulary is not None and not isinstance(vocabulary, str):
            raise ProtocolError("request.vocabulary must be a string or null")
        if not isinstance(data["device"], str) or not data["device"]:
            raise ProtocolError("request.device must be a non-empty string")
        return cls(operation, str(data["engine_id"]), _path(data["audio_path"], "request.audio_path"), vocabulary,
                   _path(data["model_path"], "request.model_path"), _path(data["aligner_path"], "request.aligner_path", optional=True),
                   data["device"], dict(options))


@dataclass(frozen=True)
class EngineResponse:
    words: tuple[Word, ...]
    native_turns: tuple[Turn, ...] | None
    diagnostics: Mapping[str, str | float | int | bool | None]
    runtime_fingerprint: str
    error: Mapping[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"schema_version": SCHEMA_VERSION, "words": [w.to_dict() for w in self.words],
                "native_diarization": None if self.native_turns is None else {"turns": [t.to_dict() for t in self.native_turns]},
                "diagnostics": dict(self.diagnostics), "runtime_fingerprint": self.runtime_fingerprint, "error": self.error}

    @classmethod
    def from_dict(cls, raw: Any) -> "EngineResponse":
        data = _object(raw, "response")
        _fields(data, _RESPONSE_FIELDS, _RESPONSE_FIELDS, "response")
        if data["schema_version"] != SCHEMA_VERSION:
            raise ProtocolError(f"unsupported schema_version {data['schema_version']!r}")
        if not isinstance(data["words"], list):
            raise ProtocolError("response.words must be an array")
        words = tuple(_word(item, index) for index, item in enumerate(data["words"]))
        _ordered(words, "words")
        native = data["native_diarization"]
        turns = None
        if native is not None:
            native = _object(native, "response.native_diarization")
            _fields(native, {"turns"}, {"turns"}, "response.native_diarization")
            if not isinstance(native["turns"], list):
                raise ProtocolError("native turns must be an array")
            turns = tuple(_turn(item, index) for index, item in enumerate(native["turns"]))
            _ordered(turns, "turns")
        diagnostics = _object(data["diagnostics"], "response.diagnostics")
        scalar_types = (str, int, float, bool, type(None))
        if any(not isinstance(k, str) or not isinstance(v, scalar_types) for k, v in diagnostics.items()):
            raise ProtocolError("diagnostics must contain scalar values")
        for key, value in diagnostics.items():
            if isinstance(value, float):
                _finite(value, f"response.diagnostics.{key}")
        fingerprint = data["runtime_fingerprint"]
        if not isinstance(fingerprint, str) or not fingerprint:
            raise ProtocolError("runtime_fingerprint must be non-empty")
        error = data["error"]
        if error is not None:
            error = _object(error, "response.error")
            _fields(error, _ERROR_FIELDS, _ERROR_FIELDS, "response.error")
            if not isinstance(error["code"], str) or not isinstance(error["message"], str) or not isinstance(error["retryable"], bool):
                raise ProtocolError("response.error has invalid scalar fields")
            if not isinstance(error["degraded_capabilities"], list) or not all(isinstance(v, str) for v in error["degraded_capabilities"]):
                raise ProtocolError("response.error.degraded_capabilities must be strings")
        return cls(words, turns, dict(diagnostics), fingerprint, dict(error) if error else None)


def _word(raw: Any, index: int) -> Word:
    data = _object(raw, f"words[{index}]")
    _fields(data, {"start", "end", "text", "confidence", "alignment_score"}, {"start", "end", "text", "confidence", "alignment_score"}, f"words[{index}]")
    start, end = _finite(data["start"], "word.start"), _finite(data["end"], "word.end")
    if start < 0 or end < start or not isinstance(data["text"], str) or not data["text"]:
        raise ProtocolError(f"words[{index}] has invalid range or text")
    for field in ("confidence", "alignment_score"):
        if data[field] is not None:
            _finite(data[field], f"word.{field}")
    return Word.from_dict(dict(data))


def _turn(raw: Any, index: int) -> Turn:
    data = _object(raw, f"turns[{index}]")
    _fields(data, {"start", "end", "speaker"}, {"start", "end", "speaker"}, f"turns[{index}]")
    start, end = _finite(data["start"], "turn.start"), _finite(data["end"], "turn.end")
    if start < 0 or end < start or not isinstance(data["speaker"], str) or not data["speaker"]:
        raise ProtocolError(f"turns[{index}] has invalid range or speaker")
    return Turn.from_dict(dict(data))


def _ordered(items: tuple[Any, ...], where: str) -> None:
    if any(right.start < left.start for left, right in zip(items, items[1:])):
        raise ProtocolError(f"response.{where} must be ordered by start time")


def read_json(path: str | Path) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProtocolError(f"cannot read protocol JSON: {exc}") from exc


def write_json(path: str | Path, value: Mapping[str, Any]) -> None:
    Path(path).write_text(json.dumps(value, ensure_ascii=False, allow_nan=False), encoding="utf-8")
