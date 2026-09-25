"""Validated user Preferences and their one-time, local migration."""

import json
import logging
import math
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from config import get_storage_path, settings
from transcript.segments import SPEAKER_SWITCH_PENALTY as DEFAULT_SPEAKER_SWITCH_PENALTY

log = logging.getLogger(__name__)

MIN_SPEAKER_SWITCH_PENALTY = 0.0
MAX_SPEAKER_SWITCH_PENALTY = 2.0


class PreferenceMigrationError(RuntimeError):
    """Migration stopped without changing legacy files or writing Preferences."""


class ForcedAlignmentPrefs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    model: str = "mms-fa"
    device: str = "auto"


class WhisperDtwPrefs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    preset: str = ""


class DiarizationPrefs(BaseModel):
    model_config = ConfigDict(extra="forbid")

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
    default_vocabulary: str = Field(default="", max_length=2000)
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
    return Path(legacy_preferences_path) if legacy_preferences_path is not None else Path.cwd() / "preferences.json"


def _migrate_if_needed(
    destination: Path,
    *,
    legacy_preferences_path: Path,
    storage_dir: Path,
) -> None:
    if destination.exists():
        return

    legacy_settings = storage_dir / "settings.json"
    entries = []
    for source in (legacy_preferences_path, legacy_settings):
        backup = source.with_name(source.name + ".migrated")
        if source.exists() and backup.exists():
            raise PreferenceMigrationError("Both a legacy source and its .migrated archive exist")
        if source.exists():
            entries.append((source, backup, False))
        elif backup.exists():
            # Recover a process interruption that happened after archival but
            # before the canonical file was installed.
            entries.append((backup, backup, True))

    data: dict[str, Any] = {}
    try:
        root_entry = next((entry for entry in entries if entry[0] in {
            legacy_preferences_path,
            legacy_preferences_path.with_name(legacy_preferences_path.name + ".migrated"),
        }), None)
        if root_entry:
            old = json.loads(root_entry[0].read_text(encoding="utf-8"))
            if not isinstance(old, dict):
                raise PreferenceMigrationError("Legacy preferences.json must contain an object")
            # This field belongs to the retired LLM feature. It remains only in
            # the byte-for-byte .migrated archive and is never active or logged.
            old.pop("llm_api_key", None)
            data.update(old)
        settings_entry = next((entry for entry in entries if entry[0] in {
            legacy_settings,
            legacy_settings.with_name(legacy_settings.name + ".migrated"),
        }), None)
        if settings_entry:
            old_settings = json.loads(settings_entry[0].read_text(encoding="utf-8"))
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

    try:
        parsed = Preferences.model_validate(data)
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
            parsed = Preferences.model_validate(repaired)
        except ValidationError as retry_error:
            raise PreferenceMigrationError(
                "Legacy Preferences could not be validated without losing a user value"
            ) from retry_error

    storage_dir.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f"{destination.name}.{uuid4().hex}.tmp")

    archived = []
    try:
        temporary.write_text(
            json.dumps(parsed.model_dump(mode="json", exclude_none=True), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        for source, backup, already_archived in entries:
            if not already_archived:
                source.replace(backup)
                archived.append((source, backup))
        temporary.replace(destination)
    except OSError as exc:
        # Roll back successful source renames before reporting failure. If a
        # rollback itself fails, the .migrated file remains a recovery source
        # for the next load because the canonical destination was not installed.
        for source, backup in reversed(archived):
            try:
                if backup.exists() and not source.exists():
                    backup.replace(source)
            except OSError:
                log.error("Could not restore a legacy Preferences archive; it remains recoverable")
        temporary.unlink(missing_ok=True)
        # The destination was absent on entry, so any file at this point came
        # from this failed attempt and must not cause a later load to skip recovery.
        destination.unlink(missing_ok=True)
        raise PreferenceMigrationError(
            "Could not complete Preferences migration; legacy data was preserved for retry"
        ) from exc
    if entries:
        log.info("Migrated legacy Preferences from %s", ", ".join(str(source) for source, _, _ in entries))


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


def update_from_settings_api(body: dict) -> Preferences:
    """Keep the existing settings endpoint's ignore/clamp behavior in one place."""
    patch: dict[str, Any] = {}
    if "default_vocabulary" in body:
        patch["default_vocabulary"] = (body["default_vocabulary"] or "").strip()[:2000]
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
        bounds = {"clustering_threshold": (0.0, 1.0), "Fa": (0.0, 5.0), "Fb": (0.0, 5.0)}
        clean = {}
        for key, (low, high) in bounds.items():
            value = raw.get(key)
            if value is None or value == "":
                continue
            try:
                number = float(value)
            except (TypeError, ValueError):
                continue
            if math.isfinite(number) and low <= number <= high:
                clean[key] = number
        patch["diarization"] = clean
    if "speaker_switch_penalty" in body:
        try:
            penalty = float(body["speaker_switch_penalty"])
        except (TypeError, ValueError):
            penalty = None
        if (
            penalty is not None
            and math.isfinite(penalty)
            and MIN_SPEAKER_SWITCH_PENALTY <= penalty <= MAX_SPEAKER_SWITCH_PENALTY
        ):
            patch["speaker_switch_penalty"] = penalty
    if "forced_alignment" in body:
        raw_alignment = body["forced_alignment"]
        if isinstance(raw_alignment, dict):
            patch["forced_alignment"] = {
                "enabled": bool(raw_alignment.get("enabled", False)),
                "model": str(raw_alignment.get("model", "mms-fa")),
                "device": str(raw_alignment.get("device", "auto")),
            }
        elif isinstance(raw_alignment, bool):
            patch["forced_alignment"] = {
                "enabled": raw_alignment,
                "model": "mms-fa",
                "device": "auto",
            }
    return update(patch)


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
