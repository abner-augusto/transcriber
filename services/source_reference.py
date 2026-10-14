"""Source References: how the app finds the original recording of a Meeting (plan 046).

The originals live outside the app. A reference holds the identity of each one (name, size
and a fast hash) and the absolute path it was last seen at. Every function here only
reads: a user's original is never moved, modified or deleted.

The hash is SHA-256 over the file's size, its first 4 MiB and its last 4 MiB (the whole file
up to 8 MiB). A full hash of a 1.5 GB WAV costs seconds and would run at upload, at every
re-point and at every search candidate. The head holds the container header, the tail
changes under truncation or re-encoding, and the size is mixed in. An edit in the middle
that keeps the size goes unnoticed; originals are not edited in place.
"""

import hashlib
import logging
import os
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

SAMPLE_BYTES = 4 * 1024 * 1024


def _hash(path: Path, size: int) -> str:
    digest = hashlib.sha256(size.to_bytes(8, "big"))
    with open(path, "rb") as handle:
        if size <= 2 * SAMPLE_BYTES:
            digest.update(handle.read())
        else:
            digest.update(handle.read(SAMPLE_BYTES))
            handle.seek(size - SAMPLE_BYTES)
            digest.update(handle.read(SAMPLE_BYTES))
    return digest.hexdigest()


def reference(file, *, path: str | None = None, name: str | None = None) -> dict:
    """The Source Reference of ``file``, as read from disk.

    ``path`` is where the user keeps the original (None when only its name is known) and
    ``name`` its file name when that differs from ``file``'s.
    """
    file = Path(file)
    size = file.stat().st_size
    return {"path": path, "name": name or file.name, "size": size, "hash": _hash(file, size)}


def matches(file, ref: dict) -> bool:
    """Whether ``file`` is the recording ``ref`` describes: same size, then same hash."""
    try:
        file = Path(file)
        return (
            file.is_file()
            and file.stat().st_size == ref["size"]
            and _hash(file, ref["size"]) == ref["hash"]
        )
    except OSError:
        return False


def find(ref: dict, roots) -> Path | None:
    """Where the recording is now: its saved path, else a file under one of ``roots``.

    A candidate under a root needs the same size and hash; its name does not matter.
    """
    if ref.get("path") and matches(ref["path"], ref):
        return Path(ref["path"])
    for root in roots:
        for directory, _names, files in os.walk(root, onerror=lambda error: None):
            for name in files:
                candidate = Path(directory) / name
                try:
                    if candidate.stat().st_size != ref["size"]:
                        continue
                except OSError:
                    continue
                if matches(candidate, ref):
                    return candidate
    return None


class SourceError(RuntimeError):
    """A Source Reference operation the user must correct; carries the HTTP status to answer."""

    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.message = message


def describe(refs: dict | None) -> list[dict]:
    """Each reference with its state, for the Meeting page. Stats the file, never hashes it.

    ``present``: the saved path exists with the stored size. ``missing``: it does not, or
    the size differs. ``not saved``: only the name is known.
    """
    described = []
    for track, ref in (refs or {}).items():
        path = ref.get("path")
        if not path:
            state = "not saved"
        else:
            try:
                state = "present" if os.stat(path).st_size == ref["size"] else "missing"
            except OSError:
                state = "missing"
        described.append({
            "track": track, "name": ref["name"], "size": ref["size"], "path": path, "state": state,
        })
    return described


def _checked_file(value: str) -> Path:
    if not os.path.isabs(value):
        raise SourceError(400, f"The path must be absolute, got '{value}'.")
    path = Path(value)
    if not path.is_file():
        raise SourceError(400, f"'{value}' is not a file.")
    return path


def repoint(meeting, source: str | None, system_source: str | None, *, adopt: bool, duration_of) -> dict:
    """The Meeting's references after pointing them at ``source`` / ``system_source``.

    ``source`` is the ``audio`` or ``mic`` file and ``system_source`` the ``system`` one.
    A file must be the recording the stored reference describes. A Meeting with no
    reference has nothing to compare with: ``adopt`` accepts the file when its duration
    (``duration_of(path)``) is within max(2 s, 1%) of the Meeting's. Raises SourceError
    and changes nothing.
    """
    if not source and not system_source:
        raise SourceError(400, "Give the new location: source, and system_source for a second track.")
    files = {
        key: _checked_file(value)
        for key, value in (("source", source), ("system_source", system_source))
        if value
    }
    refs = dict(meeting.source_refs or {})

    if refs:
        if system_source and "audio" in refs:
            raise SourceError(400, "This Meeting has one source file; system_source does not apply.")
        roles = {"source": "audio" if "audio" in refs else "mic", "system_source": "system"}
        updated = dict(refs)
        for key, file in files.items():
            ref = refs[roles[key]]
            if not matches(file, ref):
                raise SourceError(
                    409, f"'{file}' is not the same recording as {ref['name']} "
                    "(its size or content differs from what was uploaded)."
                )
            updated[roles[key]] = {**ref, "path": str(file)}
        return updated

    if not adopt:
        raise SourceError(
            400, "This Meeting has no Source Reference to compare the file with (it was uploaded "
            "before references existed). Pass adopt (CLI: --adopt) to accept the file as its recording."
        )
    if system_source and not meeting.is_dual_track:
        raise SourceError(400, "This Meeting is single-track; system_source does not apply.")
    if system_source and not source:
        raise SourceError(400, "Adopting two tracks needs both source (the mic) and system_source.")
    if meeting.duration:
        tolerance = max(2.0, 0.01 * meeting.duration)
        for file in files.values():
            found = duration_of(str(file))
            if abs(found - meeting.duration) > tolerance:
                raise SourceError(
                    409, f"'{file}' lasts {found:.0f} s but this Meeting lasts {meeting.duration:.0f} s; "
                    "its duration does not match, so it is not accepted as the recording."
                )
    roles = ("mic", "system") if system_source else ("audio",)
    return {
        role: reference(file, path=str(file))
        for role, file in zip(roles, files.values())
    }


@dataclass(frozen=True)
class Tracks:
    """Where a dual-track Meeting's mic and system recordings are now (the same file for a
    stereo original). ``held`` is true for tracks the app still stores itself."""

    mic: Path
    system: Path
    held: bool


def _flag(track: str) -> str:
    return "--system-source" if track == "system" else "--source"


def locate_tracks(meeting, roots=None) -> Tracks:
    """The mic and system recordings of a dual-track Meeting, found or raised as SourceError.

    The tracks the app still holds win. Otherwise each Source Reference is resolved with
    ``find`` (saved path, then ``roots``, which default to the ``source_roots`` Preference),
    and a path found by search is written back into ``meeting.source_refs`` for the caller
    to commit. 400 when the Meeting has no reference, 409 when one cannot be found.
    """
    mic, system = meeting.mic_audio_filepath, meeting.system_audio_filepath
    if mic and system and os.path.exists(mic) and os.path.exists(system):
        return Tracks(Path(mic), Path(system), held=True)

    refs = meeting.source_refs
    if not refs:
        raise SourceError(
            400,
            "This dual-track Meeting no longer has its mic and system tracks (the app keeps only "
            "the mixed audio once a Meeting is processed) and has no reference to its original "
            "recording, because it was uploaded before references existed. Point it at the "
            f"original: transcriber_cli set {meeting.id} --source PATH --adopt "
            "(and --system-source PATH for a second track).",
        )
    if roots is None:
        import preferences
        roots = preferences.load().source_roots

    found, healed = {}, dict(refs)
    for track, ref in refs.items():
        path = find(ref, roots)
        if path is None:
            raise SourceError(
                409,
                f"The original recording {ref['name']} was not found"
                + (f" at {ref['path']}" if ref.get("path") else "")
                + (" or in the search folders" if roots else "")
                + f". Point the Meeting at it again: transcriber_cli set {meeting.id} "
                f"{_flag(track)} NEW_PATH (or use Sources on the Meeting page).",
            )
        found[track] = path
        if str(path) != ref.get("path"):
            healed[track] = {**ref, "path": str(path)}
    if healed != refs:
        meeting.source_refs = healed
    return Tracks(
        found.get("mic") or found["audio"], found.get("system") or found["audio"], held=False
    )
