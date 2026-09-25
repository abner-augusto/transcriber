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


def resolve_run_config(preset_id: str | None, *, preferences: Preferences | None = None) -> RunConfig:
    """Capture the Preferences and the Preset that apply when a Job begins running.

    ``preset_id`` is the Meeting's chosen Preset, or None for the default one.
    """
    import presets

    prefs = preferences or load()
    preset = dict(presets.resolve_preset(preset_id, default_preset=prefs.default_preset))

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
