"""Validated user Preferences and their one-time, local migration."""

import json
import logging
import math
from pathlib import Path
from typing import Any, Literal, get_args
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from config import get_storage_path, settings
from engines import DEFAULT_ALIGNMENT_ENGINE
from transcript.segments import SPEAKER_SWITCH_PENALTY as DEFAULT_SPEAKER_SWITCH_PENALTY

log = logging.getLogger(__name__)

MIN_SPEAKER_SWITCH_PENALTY = 0.0
MAX_SPEAKER_SWITCH_PENALTY = 2.0
MAX_DEFAULT_VOCABULARY_LENGTH = 2000


# Where releases before plan 016 kept Preferences: the repository root, which is
# this module's directory, whatever the working directory of the process.
LEGACY_PREFERENCES_PATH = Path(__file__).resolve().parent / "preferences.json"


class PreferenceMigrationError(RuntimeError):
    """Migration stopped without changing legacy files or writing Preferences."""


class ForcedAlignmentPrefs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    model: str = DEFAULT_ALIGNMENT_ENGINE
    device: str = "auto"


class WhisperDtwPrefs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    preset: str = ""


class DiarizationPrefs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    engine: Literal["pyannote", "nemotron-3-diarization"] = "pyannote"
    clustering_threshold: float | None = Field(default=None, ge=0.0, le=1.0)
    Fa: float | None = Field(default=None, ge=0.0, le=5.0)
    Fb: float | None = Field(default=None, ge=0.0, le=5.0)


class VocabularyCorrectionPrefs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True


class VocabularyProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    terms: str


class Preferences(BaseModel):
    model_config = ConfigDict(extra="forbid")

    default_preset: str | None = None
    default_vocabulary: str = Field(default="", max_length=MAX_DEFAULT_VOCABULARY_LENGTH)
    speaker_profiles_enabled: bool = False
    hf_auth_token: str = ""
    speaker_switch_penalty: float = Field(
        default=DEFAULT_SPEAKER_SWITCH_PENALTY,
        ge=MIN_SPEAKER_SWITCH_PENALTY,
        le=MAX_SPEAKER_SWITCH_PENALTY,
    )
    forced_alignment: ForcedAlignmentPrefs = Field(default_factory=ForcedAlignmentPrefs)
    whisper_dtw: WhisperDtwPrefs = Field(default_factory=WhisperDtwPrefs)
    diarization: DiarizationPrefs = Field(default_factory=DiarizationPrefs)
    vocabulary_profiles: list[VocabularyProfile] = Field(default_factory=list)
    vocabulary_correction: VocabularyCorrectionPrefs = Field(
        default_factory=VocabularyCorrectionPrefs
    )


def _preference_path(storage_dir: Path | None = None) -> Path:
    return (Path(storage_dir) if storage_dir is not None else get_storage_path()) / "preferences.json"


def _legacy_path(legacy_preferences_path: Path | None = None) -> Path:
    return Path(legacy_preferences_path) if legacy_preferences_path is not None else LEGACY_PREFERENCES_PATH


def _migrate_if_needed(
    destination: Path,
    *,
    legacy_preferences_path: Path,
    storage_dir: Path,
) -> None:
    """Merge the legacy files into ``destination``, install it, then archive them.

    The canonical file is installed before any legacy file is renamed, so an
    interruption at any point leaves either the untouched legacy files or a
    complete canonical file. Once installed, the legacy files are never read
    again, even if the canonical file is later deleted to reset Preferences.
    """
    if destination.exists():
        return

    legacy_settings = storage_dir / "settings.json"
    sources = [source for source in (legacy_preferences_path, legacy_settings) if source.exists()]
    for source in sources:
        if _archive_path(source).exists():
            raise PreferenceMigrationError("Both a legacy source and its .migrated archive exist")

    data: dict[str, Any] = {}
    try:
        if legacy_preferences_path.exists():
            old = json.loads(legacy_preferences_path.read_text(encoding="utf-8"))
            if not isinstance(old, dict):
                raise PreferenceMigrationError("Legacy preferences.json must contain an object")
            # This field belongs to the retired LLM feature. It remains only in
            # the byte-for-byte .migrated archive and is never active or logged.
            old.pop("llm_api_key", None)
            data.update(old)
        if legacy_settings.exists():
            old_settings = json.loads(legacy_settings.read_text(encoding="utf-8"))
            if not isinstance(old_settings, dict):
                raise PreferenceMigrationError("Legacy settings.json must contain an object")
            unknown = set(old_settings) - {"default_preset"}
            if unknown:
                raise PreferenceMigrationError(
                    f"Unrecognized legacy settings fields would be lost: {sorted(unknown)}"
                )
            if "default_preset" in old_settings:
                data["default_preset"] = old_settings["default_preset"]
    except (json.JSONDecodeError, OSError) as exc:
        raise PreferenceMigrationError(f"Could not safely read legacy Preferences: {exc}") from exc

    parsed = _validate_legacy(data)

    storage_dir.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f"{destination.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_text(
            json.dumps(parsed.model_dump(mode="json", exclude_none=True), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        temporary.replace(destination)
    except OSError as exc:
        temporary.unlink(missing_ok=True)
        raise PreferenceMigrationError(
            "Could not write Preferences; the legacy files were left untouched"
        ) from exc

    for source in sources:
        try:
            source.replace(_archive_path(source))
        except OSError:
            log.warning("Could not archive legacy Preferences %s; it is no longer read", source)
    if sources:
        log.info("Migrated legacy Preferences from %s", ", ".join(str(source) for source in sources))


def _archive_path(source: Path) -> Path:
    return source.with_name(source.name + ".migrated")


def _validate_legacy(data: dict[str, Any]) -> Preferences:
    try:
        return Preferences.model_validate(data)
    except ValidationError as exc:
        # A bound violation can be repaired by dropping just that value. Any other
        # validation error is a STOP: preserve the sources for user review.
        repaired = dict(data)
        drop_paths = []
        for error in exc.errors():
            error_type = error["type"]
            if error_type not in {"greater_than_equal", "less_than_equal", "string_too_long"}:
                raise PreferenceMigrationError(
                    "Legacy Preferences contain a value this model cannot preserve; "
                    "the legacy files were left untouched"
                ) from exc
            drop_paths.append(tuple(error["loc"]))
        for path in drop_paths:
            parent = repaired
            for part in path[:-1]:
                parent = parent.get(part, {}) if isinstance(parent, dict) else {}
            if isinstance(parent, dict):
                parent.pop(path[-1], None)
            log.warning("Dropped out-of-bounds legacy Preference field %s", ".".join(map(str, path)))
        try:
            return Preferences.model_validate(repaired)
        except ValidationError as retry_error:
            raise PreferenceMigrationError(
                "Legacy Preferences could not be validated without losing a user value"
            ) from retry_error


def load(
    *, storage_dir: Path | None = None, legacy_preferences_path: Path | None = None
) -> Preferences:
    storage = Path(storage_dir) if storage_dir is not None else get_storage_path()
    path = _preference_path(storage)
    _migrate_if_needed(
        path,
        legacy_preferences_path=_legacy_path(legacy_preferences_path),
        storage_dir=storage,
    )
    if not path.exists():
        return Preferences()
    data = json.loads(path.read_text(encoding="utf-8"))
    return Preferences.model_validate(data)


def update(
    patch: dict,
    *,
    storage_dir: Path | None = None,
    legacy_preferences_path: Path | None = None,
) -> Preferences:
    current = load(
        storage_dir=storage_dir,
        legacy_preferences_path=legacy_preferences_path,
    )
    data = current.model_dump(mode="json", exclude_none=True)
    data.update(patch)
    updated = Preferences.model_validate(data)
    destination = _preference_path(storage_dir)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(updated.model_dump(mode="json", exclude_none=True), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return updated


def apply_preferences_request(body: dict) -> Preferences:
    """Apply a PUT /api/settings/preferences body.

    The route's contract is to ignore a value it cannot use rather than reject
    the request; bounds come from the models, so they are stated once.
    """
    patch: dict[str, Any] = {}
    if "default_vocabulary" in body:
        patch["default_vocabulary"] = (body["default_vocabulary"] or "").strip()[:MAX_DEFAULT_VOCABULARY_LENGTH]
    if "speaker_profiles_enabled" in body:
        patch["speaker_profiles_enabled"] = bool(body["speaker_profiles_enabled"])
    if isinstance(body.get("vocabulary_correction"), dict):
        enabled = body["vocabulary_correction"].get("enabled")
        if isinstance(enabled, bool):
            patch["vocabulary_correction"] = {"enabled": enabled}
    if "hf_auth_token" in body:
        value = (body["hf_auth_token"] or "").strip()
        if value and "*" not in value:
            patch["hf_auth_token"] = value
    if "diarization" in body:
        raw = body["diarization"] if isinstance(body["diarization"], dict) else {}
        diarization_patch = {
            key: number
            for key in DiarizationPrefs.model_fields
            if (number := _accepted_number(DiarizationPrefs, key, raw.get(key))) is not None
        }
        # The patch replaces the whole block, so an absent or unknown engine keeps the stored one.
        engine = raw.get("engine")
        supported = get_args(DiarizationPrefs.model_fields["engine"].annotation)
        diarization_patch["engine"] = engine if engine in supported else load().diarization.engine
        patch["diarization"] = diarization_patch
    if "speaker_switch_penalty" in body:
        penalty = _accepted_number(Preferences, "speaker_switch_penalty", body["speaker_switch_penalty"])
        if penalty is not None:
            patch["speaker_switch_penalty"] = penalty
    if "forced_alignment" in body:
        raw_alignment = body["forced_alignment"]
        if isinstance(raw_alignment, bool):
            raw_alignment = {"enabled": raw_alignment}
        if isinstance(raw_alignment, dict):
            patch["forced_alignment"] = {
                **ForcedAlignmentPrefs().model_dump(),
                **{key: str(raw_alignment[key]) for key in ("model", "device") if key in raw_alignment},
                "enabled": bool(raw_alignment.get("enabled", False)),
            }
    return update(patch)


def _accepted_number(model: type[BaseModel], field: str, value) -> float | None:
    """``value`` as a finite float the model's field accepts, else None."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    try:
        model.__pydantic_validator__.validate_assignment(model.model_construct(), field, number)
    except ValidationError:
        return None
    return number


def public(*, storage_dir: Path | None = None) -> dict:
    data = load(storage_dir=storage_dir).model_dump(mode="json", exclude_none=True)
    # The model-settings route already owns the legacy location for this field.
    # Keeping it out preserves GET /api/settings' response shape.
    data.pop("default_preset", None)
    token = data.get("hf_auth_token", "")
    if token:
        data["hf_auth_token"] = token[:3] + "*" * 10 + token[-3:] if len(token) > 6 else "*" * 10
    return data


def hf_token(*, storage_dir: Path | None = None) -> str:
    return load(storage_dir=storage_dir).hf_auth_token or settings.hf_auth_token
