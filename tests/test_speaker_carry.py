from transcript.speaker_carry import match_by_overlap


def test_identical_intervals_under_swapped_labels_map_across():
    old = {"SPEAKER_00": [(0.0, 10.0)], "SPEAKER_01": [(10.0, 20.0)]}
    new = {"SPEAKER_00": [(10.0, 20.0)], "SPEAKER_01": [(0.0, 10.0)]}

    assert match_by_overlap(old, new) == {"SPEAKER_00": "SPEAKER_01", "SPEAKER_01": "SPEAKER_00"}


def test_a_forty_percent_overlap_does_not_match():
    old = {"A": [(0.0, 10.0)]}
    new = {"X": [(6.0, 16.0)]}

    assert match_by_overlap(old, new) == {}


def test_exactly_half_of_the_old_time_matches():
    old = {"A": [(0.0, 10.0)]}
    new = {"X": [(5.0, 15.0)]}

    assert match_by_overlap(old, new) == {"A": "X"}


def test_two_old_labels_competing_for_one_new_label_match_only_the_mutual_best():
    old = {"A": [(0.0, 10.0)], "B": [(10.0, 14.0)]}
    new = {"X": [(0.0, 14.0)]}

    assert match_by_overlap(old, new) == {"A": "X"}


def test_a_new_label_split_across_two_old_ones_is_not_a_mutual_best_for_the_smaller():
    old = {"A": [(0.0, 10.0)]}
    new = {"X": [(0.0, 6.0)], "Y": [(6.0, 10.0)]}

    assert match_by_overlap(old, new) == {"A": "X"}


def test_empty_inputs_give_nothing():
    assert match_by_overlap({}, {}) == {}
    assert match_by_overlap({"A": [(0.0, 1.0)]}, {}) == {}
    assert match_by_overlap({}, {"X": [(0.0, 1.0)]}) == {}


def test_an_old_label_with_no_speaking_time_matches_nothing():
    assert match_by_overlap({"A": []}, {"X": [(0.0, 1.0)]}) == {}


def test_ties_go_to_the_alphabetically_first_label():
    old = {"A": [(0.0, 10.0)]}
    new = {"Y": [(0.0, 5.0)], "X": [(5.0, 10.0)]}

    assert match_by_overlap(old, new) == {"A": "X"}
