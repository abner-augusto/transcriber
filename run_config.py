"""Resolve all result-affecting user choices into a per-Job snapshot."""

from typing import Any

from pydantic import BaseModel, ConfigDict

from preferences import (
    DiarizationPrefs,
    ForcedAlignmentPrefs,
    Preferences,
    VocabularyCorrectionPrefs,
    WhisperDtwPrefs,
    load,
)


class RunConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    preset: dict[str, Any]
    forced_alignment: ForcedAlignmentPrefs | None = None
    whisper_dtw: WhisperDtwPrefs
    diarization: DiarizationPrefs
    speaker_switch_penalty: float
    speaker_profiles_enabled: bool
    vocabulary_correction: VocabularyCorrectionPrefs


def resolve_run_config(meeting, *, preferences: Preferences | None = None) -> RunConfig:
    """Capture the Preferences and Preset that apply when a Job begins running."""
    import presets

    prefs = preferences or load()
    preset = dict(
        presets.resolve_preset(meeting.preset_id, default_preset=prefs.default_preset)
    )

    raw_alignment = preset.get("forced_alignment")
    alignment_enabled = bool(raw_alignment) or prefs.forced_alignment.enabled
    alignment_config = prefs.forced_alignment.model_dump()
    if isinstance(raw_alignment, dict):
        alignment_config.update(raw_alignment)
    alignment = (
        ForcedAlignmentPrefs.model_validate({**alignment_config, "enabled": True})
        if alignment_enabled
        else None
    )

    dtw_enabled = preset.get("dtw", prefs.whisper_dtw.enabled)
    dtw_preset = preset.get("dtw_preset", prefs.whisper_dtw.preset)
    dtw = WhisperDtwPrefs(enabled=bool(dtw_enabled), preset=dtw_preset or "")

    return RunConfig(
        preset=preset,
        forced_alignment=alignment,
        whisper_dtw=dtw,
        diarization=prefs.diarization,
        speaker_switch_penalty=prefs.speaker_switch_penalty,
        speaker_profiles_enabled=prefs.speaker_profiles_enabled,
        vocabulary_correction=prefs.vocabulary_correction,
    )


def run_config_for_preset(preset: dict, *, preferences: Preferences | None = None) -> RunConfig:
    """Build the same snapshot for a standalone local Engine tool or bench row."""
    from types import SimpleNamespace

    return resolve_run_config(SimpleNamespace(preset_id=preset["id"]), preferences=preferences)
