"""The Diarization stage: how a Meeting gets its Turns.

There are three ways, and every Job that needs Turns comes through here:

- a dual-track Meeting names the local mic speaker from VAD on the mic track and runs
  the Diarizer on the system track only;
- a Transcriber with native diarization (VibeVoice) has already produced Turns;
- otherwise the Diarizer runs over the Meeting's audio.

Single-track Turns are then bounded to the speech VAD finds. The stage neither
persists its result; the child process releases model memory when the Job exits.
"""

import logging
from collections.abc import Callable

from config import get_meeting_path
from engines import DIARIZER_ENGINE, DiarizationResult, Turn, compute_overlaps
from services.audio_service import DUAL_MIC_OUTPUT, DUAL_SYSTEM_OUTPUT
from transcript.diarization import MeetingDiarization

from .dual_track import HOST_SPEAKER, build_dual_diarization, host_turns_from_vad

log = logging.getLogger(__name__)


def diarize_meeting(
    meeting,
    audio_path: str,
    *,
    diarizer,
    vad_service,
    native: DiarizationResult | None = None,
    on_path: Callable[[str], None] | None = None,
) -> MeetingDiarization:
    """The Turns for ``meeting``. A dual-track Meeting ignores ``native``.

    ``meeting`` needs ``id``, ``is_dual_track``, ``min_speakers`` and ``max_speakers``.
    Raises RuntimeError when a dual-track Meeting's processed tracks are missing.
    """
    if meeting.is_dual_track:
        if on_path:
            on_path("dual_track")
        return _diarize_dual_track(meeting, diarizer, vad_service)
    if native is not None:
        if not native.engine:
            raise ValueError("native Turns must name the Engine that produced them")
        if on_path:
            on_path("native")
        return bound_to_speech(native, audio_path, vad_service, engine=native.engine)
    if on_path:
        on_path("diarizer")
    result = _as_result(diarizer.diarize(
        audio_path,
        min_speakers=meeting.min_speakers,
        max_speakers=meeting.max_speakers,
    ))
    return bound_to_speech(result, audio_path, vad_service, engine=result.engine or DIARIZER_ENGINE)


def bound_to_speech(result, audio_path: str, vad_service, *, engine: str) -> MeetingDiarization:
    """Bound Turns — from the Diarizer or a Transcriber's native diarization — to the speech
    VAD finds, keeping the originals alongside."""
    original = _as_result(result)
    vad_segments = vad_service.compute_vad_segments(audio_path)
    if vad_segments:
        turns = vad_service.mask_turns_to_vad(original.turns, vad_segments)
        exclusive = (
            vad_service.mask_turns_to_vad(original.exclusive_turns, vad_segments)
            if original.exclusive_turns is not None
            else None
        )
    else:
        log.warning("VAD returned no speech bounds; keeping original diarization Turns")
        turns = list(original.turns)
        exclusive = list(original.exclusive_turns) if original.exclusive_turns is not None else None

    return MeetingDiarization(
        engine=engine,
        turns=turns,
        exclusive_turns=exclusive,
        overlaps=compute_overlaps(turns),
        original_turns=list(original.turns),
        original_exclusive_turns=(
            list(original.exclusive_turns) if original.exclusive_turns is not None else None
        ),
        original_overlaps=(
            original.overlaps if original.overlaps is not None else compute_overlaps(original.turns)
        ),
    )


def _diarize_dual_track(meeting, diarizer, vad_service) -> MeetingDiarization:
    meeting_dir = get_meeting_path(meeting.id)
    mic_path = meeting_dir / DUAL_MIC_OUTPUT
    system_path = meeting_dir / DUAL_SYSTEM_OUTPUT
    for path in (mic_path, system_path):
        if not path.exists():
            raise RuntimeError(
                f"Dual-track track not found: {path}. Diarizing a dual-track Meeting "
                "needs the processed tracks its first Job extracted."
            )

    # Host: every speech region on the mic track is the host, with no clustering.
    host_turns = host_turns_from_vad(vad_service.compute_vad_segments(str(mic_path)))

    # Remote: the Diarizer on the system track, bounded by VAD on that track.
    remote = _as_result(diarizer.diarize(
        str(system_path),
        min_speakers=meeting.min_speakers,
        max_speakers=meeting.max_speakers,
    ))
    system_vad = vad_service.compute_vad_segments(str(system_path))
    remote_turns = vad_service.mask_turns_to_vad(remote.turns, system_vad)

    merged = build_dual_diarization(host_turns, remote_turns)
    return MeetingDiarization(
        engine=remote.engine or DIARIZER_ENGINE,
        turns=merged.turns,
        exclusive_turns=merged.exclusive_turns,
        overlaps=merged.overlaps,
        host_label=HOST_SPEAKER,
    )


def _as_result(result) -> DiarizationResult:
    """A Diarizer may return a DiarizationResult, its stored dict, or a bare list of Turns."""
    if isinstance(result, DiarizationResult):
        return result
    if isinstance(result, dict):
        exclusive = result.get("exclusive_turns")
        return DiarizationResult(
            turns=[Turn.from_dict(t) for t in result.get("turns", [])],
            exclusive_turns=[Turn.from_dict(t) for t in exclusive] if exclusive is not None else None,
            overlaps=result.get("overlaps"),
        )
    return DiarizationResult(turns=list(result))
