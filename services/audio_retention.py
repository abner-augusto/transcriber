"""What a Meeting's folder keeps once it is processed: the derived ``audio.wav`` only.

The original recordings live outside the app, in the project folder of each meeting
(plan 045). Everything below is dropped when a Job finishes: the uploaded sources and the
intermediate tracks AudioService made from them. Add any new artifact AudioService writes
to the Meeting folder here, or it will accumulate again.
"""

import logging
from pathlib import Path

from config import get_meeting_path
from services.audio_service import DUAL_MIC_OUTPUT, DUAL_SYSTEM_OUTPUT, MIX_PART_OUTPUT

log = logging.getLogger(__name__)

# Upload names: ``api.meetings.create_meeting`` saves them as ``<stem><container extension>``.
DROPPED_STEMS = ("original", "mic_source", "system_source")
DROPPED_NAMES = (DUAL_MIC_OUTPUT, DUAL_SYSTEM_OUTPUT)
# A mix ffmpeg was writing when its Job was stopped (see ``AudioService.extract_dual_audio``).
PARTIAL_NAMES = (MIX_PART_OUTPUT,)


def forget_raw_audio(meeting) -> None:
    """Forget the source paths of a Meeting whose sources are about to be deleted.

    Part of the Job's final transaction; ``delete_raw_audio`` follows once it is committed.
    """
    meeting.mic_audio_filepath = None
    meeting.system_audio_filepath = None


def delete_raw_audio(meeting_id: str, audio_filepath: str | None) -> None:
    """Delete a Meeting's sources and processed tracks, after its Job committed.

    Only files named above inside the Meeting's own folder are deleted, never the file
    ``audio_filepath`` names. A file that cannot be deleted is logged and left; the step
    never fails the Job that called it.
    """
    directory = get_meeting_path(meeting_id)
    played = _resolved(audio_filepath)
    doomed = [
        path for path in directory.iterdir()
        if path.is_file()
        and (path.stem in DROPPED_STEMS or path.name in (*DROPPED_NAMES, *PARTIAL_NAMES))
        and path.resolve() != played
    ]
    for path in doomed:
        try:
            path.unlink()
        except OSError as exc:
            log.warning("Could not delete %s: %s", path, exc)


def drop_cancelled_work(meeting, *, keep_audio: bool) -> None:
    """Delete what a Job that was stopped left in the Meeting's folder (plan 048).

    The processed tracks and a half-written mix always go. ``audio.wav`` goes too unless
    ``keep_audio`` (the Meeting went back to COMPLETED and plays it) or the Meeting's
    ``audio_filepath`` names it. The uploads (``original.*``, ``mic_source.*``,
    ``system_source.*``) are never touched: they are what an UPLOADED Meeting starts from
    again. A file that cannot be deleted is logged and left.
    """
    directory = get_meeting_path(meeting.id)
    played = _resolved(meeting.audio_filepath)
    names = [*DROPPED_NAMES, *PARTIAL_NAMES, *(() if keep_audio else ("audio.wav",))]
    for name in names:
        path = directory / name
        try:
            if path.is_file() and path.resolve() != played:
                path.unlink()
        except OSError as exc:
            log.warning("Could not delete %s: %s", path, exc)


def drop_processed_tracks(meeting_id: str) -> None:
    """Delete only the two processed tracks, for a Job that made them just to read them."""
    directory = get_meeting_path(meeting_id)
    for name in DROPPED_NAMES:
        try:
            (directory / name).unlink(missing_ok=True)
        except OSError as exc:
            log.warning("Could not delete %s: %s", directory / name, exc)


def processed_tracks_present(meeting_id: str) -> bool:
    """Whether the Meeting's folder still holds both processed tracks a dual-track
    Re-diarize reads."""
    directory = get_meeting_path(meeting_id)
    return all((directory / name).exists() for name in DROPPED_NAMES)


def _resolved(path: str | None) -> Path | None:
    return Path(path).resolve() if path else None
