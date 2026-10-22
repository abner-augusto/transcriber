"""Telling a microphone from a desktop-audio track from a mix, by the samples alone.

Independent noise stands in for two different speakers: it is uncorrelated with itself by
construction, which is what separate recordings of different sources are.
"""

import numpy as np
import pytest

from services.track_analysis import assign_roles, classify, speech_candidates

RNG = np.random.default_rng(7)
N = 8000 * 30  # 30 s at 8 kHz


def voice(level: float = 0.1) -> np.ndarray:
    return (RNG.standard_normal(N) * level).astype(np.float32)


def test_two_different_sources_are_both_speech():
    assert classify([voice(), voice()]) == ["speech", "speech"]


def test_a_silent_track_is_silent():
    assert classify([voice(), np.zeros(N, np.float32)]) == ["speech", "silent"]


def test_a_barely_audible_noise_floor_is_silent():
    assert classify([voice(), voice(level=1e-5)]) == ["speech", "silent"]


def test_identical_channels_of_a_fake_stereo_are_one_track():
    left = voice()
    assert classify([left, left.copy()]) == ["speech", "duplicate"]


def test_a_louder_or_quieter_copy_is_still_a_duplicate():
    left = voice()
    assert classify([left, left * 0.5]) == ["speech", "duplicate"]


def test_a_nearly_identical_pair_with_a_little_noise_is_a_duplicate():
    left = voice()
    right = left + voice(level=0.002)
    assert classify([left, right]) == ["speech", "duplicate"]


def test_obs_track_one_that_is_the_sum_of_the_others_is_a_mix():
    mic, desktop = voice(), voice()
    assert classify([mic + desktop, mic, desktop]) == ["mix", "speech", "speech"]


def test_a_mix_with_unequal_gains_is_still_a_mix():
    mic, desktop = voice(), voice()
    assert classify([0.9 * mic + 0.3 * desktop, mic, desktop]) == ["mix", "speech", "speech"]


def test_the_mix_is_found_wherever_it_sits_in_the_file():
    mic, desktop = voice(), voice()
    assert classify([mic, desktop, mic + desktop]) == ["speech", "speech", "mix"]


def test_three_independent_sources_have_no_mix():
    assert classify([voice(), voice(), voice()]) == ["speech", "speech", "speech"]


def test_two_tracks_are_never_called_a_mix_of_each_other():
    mic = voice()
    assert classify([mic, voice()]) == ["speech", "speech"]


def test_a_mix_of_a_track_and_silence_is_a_duplicate_not_a_mix():
    mic = voice()
    assert classify([mic, mic.copy(), np.zeros(N, np.float32)]) == ["speech", "duplicate", "silent"]


def test_tracks_of_unequal_length_are_compared_over_the_shorter():
    a = voice()
    assert classify([a, a[: N // 2].copy()]) == ["speech", "duplicate"]


@pytest.mark.parametrize(
    "statuses, expected",
    [
        (["speech", "speech"], [0, 1]),
        (["mix", "speech", "speech"], [1, 2]),
        (["speech", "silent", "speech", "speech"], [0, 2, 3]),
        (["speech", "duplicate"], [0]),
        (["silent", "silent"], []),
    ],
)
def test_speech_candidates_are_the_indexes_to_use_in_file_order(statuses, expected):
    assert speech_candidates(statuses) == expected


# --- who is the mic, by the names the recorder gave the tracks ----------------------------

@pytest.mark.parametrize(
    "titles, expected",
    [
        # OBS in Portuguese, as recorded on this machine: the desktop comes first.
        (["Computador", "Microfone"], (1, 0)),
        (["Microphone", "Desktop Audio"], (0, 1)),
        (["Mic/Aux", "Desktop Audio"], (0, 1)),
        (["Áudio do desktop", "Microfone"], (1, 0)),
        # No names: the file's order, mic first.
        ([None, None], (0, 1)),
        (["Track 1", "Track 2"], (0, 1)),
        # One name is enough: the other track is the remaining one.
        ([None, "Microfone"], (1, 0)),
        (["Computador", None], (1, 0)),
        # Names that contradict each other are not trusted over the order.
        (["Microfone", "Microfone"], (0, 1)),
    ],
)
def test_roles_follow_the_track_names_and_fall_back_to_the_file_order(titles, expected):
    assert assign_roles(titles, list(range(len(titles)))) == expected


def test_roles_are_chosen_among_the_tracks_worth_reading_only():
    # Track 0 is a mix; the names of tracks 1 and 2 decide.
    titles = [None, "Computador", "Microfone"]
    assert assign_roles(titles, [1, 2]) == (2, 1)


def test_with_fewer_than_two_tracks_there_are_no_roles():
    assert assign_roles(["Microfone", "Computador"], [1]) is None
    assert assign_roles([], []) is None
