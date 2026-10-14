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
