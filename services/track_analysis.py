"""Telling a microphone from a desktop-audio track from a mix, by the samples alone.

A recording can carry several candidate tracks: the streams of the file, or the channels of
a stereo stream. Each is classified from a short mono sample of it:

- ``silent``: nothing recorded (a muted desktop source).
- ``duplicate``: a copy of an earlier track, however loud (a fake stereo).
- ``mix``: the sum of the others (OBS track 1 usually carries everything).
- ``speech``: a source of its own.

Pure numpy; the decoding that produces the samples lives in ``AudioService``.
"""

import numpy as np

# Below this RMS (full scale = 1.0, about -60 dBFS) a track recorded nothing.
SILENCE_RMS = 1e-3
# Correlation at or above which a track is a copy of an earlier one.
DUPLICATE_CORRELATION = 0.98
# Share of a track's variance a sum of the other tracks explains, at or above which it is their mix.
# Measured 2026-10-15: white noise, the worst case for a lossy codec, scores 0.89 after AAC
# at 128 kbit/s; independent sources score near 0.
MIX_EXPLAINED = 0.85

SPEECH, SILENT, DUPLICATE, MIX = "speech", "silent", "duplicate", "mix"


def _rms(x: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(x, dtype=np.float64)))) if x.size else 0.0


def _correlation(a: np.ndarray, b: np.ndarray) -> float:
    a = a.astype(np.float64) - a.mean()
    b = b.astype(np.float64) - b.mean()
    denominator = np.linalg.norm(a) * np.linalg.norm(b)
    return float(abs(a @ b) / denominator) if denominator else 0.0


def _is_mix_of(track: np.ndarray, others: list[np.ndarray]) -> bool:
    """Whether a positively weighted sum of ``others`` reproduces ``track``.

    The weights must all be positive: with A = B + C, B is also a combination of A and C,
    but with C subtracted, and a recorder never subtracts.
    """
    target = track.astype(np.float64) - track.mean()
    basis = np.stack([o.astype(np.float64) - o.mean() for o in others], axis=1)
    weights, *_ = np.linalg.lstsq(basis, target, rcond=None)
    residual = target - basis @ weights
    total = float(target @ target)
    explained = 1.0 - float(residual @ residual) / total if total else 0.0
    return explained >= MIX_EXPLAINED and bool(np.all(weights > 0))


def classify(tracks: list[np.ndarray]) -> list[str]:
    """The status of each track, in order. Tracks are compared over the shortest one."""
    if not tracks:
        return []
    length = min(len(t) for t in tracks)
    tracks = [t[:length] for t in tracks]

    statuses = [SILENT if _rms(t) < SILENCE_RMS else SPEECH for t in tracks]

    for i, track in enumerate(tracks):
        if statuses[i] != SPEECH:
            continue
        if any(
            statuses[j] == SPEECH and _correlation(track, tracks[j]) >= DUPLICATE_CORRELATION
            for j in range(i)
        ):
            statuses[i] = DUPLICATE

    live = [i for i, s in enumerate(statuses) if s == SPEECH]
    if len(live) >= 3:
        for i in live:
            if _is_mix_of(tracks[i], [tracks[j] for j in live if j != i]):
                statuses[i] = MIX
                break  # one mix at most; the others are its parts
    return statuses


def speech_candidates(statuses: list[str]) -> list[int]:
    """The indexes worth reading, in file order."""
    return [i for i, status in enumerate(statuses) if status == SPEECH]


# Words in the name a recorder gives a track (OBS: "Microfone", "Computador", "Desktop Audio").
MIC_NAMES = ("mic",)  # also matches "microfone", "microphone"
SYSTEM_NAMES = ("desktop", "computador", "computer", "sistema", "system", "speaker", "alto-falante")


def _named_role(title: str | None) -> str | None:
    lowered = (title or "").lower()
    if any(word in lowered for word in SYSTEM_NAMES):
        return "system"
    if any(word in lowered for word in MIC_NAMES):
        return "mic"
    return None


def assign_roles(titles: list[str | None], used: list[int]) -> tuple[int, int] | None:
    """The (mic, system) pair among the tracks worth reading, or None with fewer than two.

    The names the recorder gave the tracks decide when they are clear (one track named
    like a mic, one like a desktop); OBS puts the desktop first in some profiles. Without
    clear names the file's order does: the first track is the mic.
    """
    if len(used) < 2:
        return None
    roles = {i: _named_role(titles[i]) for i in used}
    mics = [i for i in used if roles[i] == "mic"]
    systems = [i for i in used if roles[i] == "system"]
    mic = mics[0] if len(mics) == 1 else None
    system = systems[0] if len(systems) == 1 else None
    if mic is None and system is None:
        return used[0], used[1]
    if mic is None:
        mic = next(i for i in used if i != system)
    if system is None:
        system = next(i for i in used if i != mic)
    return mic, system
