"""A Source Reference identifies an original recording by size and a fast hash."""

import os

from services import source_reference as sources

MIB = 1024 * 1024


def _write(path, head=b"H", middle=b"M", tail=b"T", size=10 * MIB):
    body = head * (4 * MIB) + middle * (size - 8 * MIB) + tail * (4 * MIB)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    return path


def test_reference_records_name_size_and_hash_but_never_the_content(tmp_path):
    file = _write(tmp_path / "mic.wav")

    ref = sources.reference(file, path=str(file))

    assert ref["name"] == "mic.wav"
    assert ref["size"] == 10 * MIB
    assert ref["path"] == str(file)
    assert len(ref["hash"]) == 64
    assert sources.reference(file)["path"] is None


def test_the_same_bytes_under_another_name_match(tmp_path):
    ref = sources.reference(_write(tmp_path / "a" / "mic.wav"))
    moved = _write(tmp_path / "b" / "renamed.wav")

    assert sources.matches(moved, ref)


def test_a_different_head_or_tail_or_size_does_not_match(tmp_path):
    ref = sources.reference(_write(tmp_path / "mic.wav"))

    assert not sources.matches(_write(tmp_path / "head.wav", head=b"X"), ref)
    assert not sources.matches(_write(tmp_path / "tail.wav", tail=b"X"), ref)
    assert not sources.matches(_write(tmp_path / "size.wav", size=11 * MIB), ref)
    assert not sources.matches(tmp_path / "absent.wav", ref)


def test_a_small_file_is_hashed_whole(tmp_path):
    a = tmp_path / "a.wav"
    b = tmp_path / "b.wav"
    a.write_bytes(b"x" * 1000 + b"1" + b"y" * 1000)
    b.write_bytes(b"x" * 1000 + b"2" + b"y" * 1000)

    assert not sources.matches(b, sources.reference(a))


def test_find_uses_the_stored_path_first(tmp_path):
    file = _write(tmp_path / "mic.wav")
    ref = sources.reference(file, path=str(file))

    assert sources.find(ref, roots=[]) == file


def test_find_returns_nothing_when_the_path_is_stale_and_no_roots_are_set(tmp_path):
    file = _write(tmp_path / "inbox" / "mic.wav")
    ref = sources.reference(file, path=str(file))
    file.unlink()

    assert sources.find(ref, roots=[]) is None


def test_find_searches_roots_by_size_then_hash_ignoring_the_name(tmp_path):
    original = _write(tmp_path / "inbox" / "mic.wav")
    ref = sources.reference(original, path=str(original))
    original.unlink()
    _write(tmp_path / "project" / "other.wav", head=b"X")  # same size, other recording
    _write(tmp_path / "project" / "small.wav", size=9 * MIB)
    moved = _write(tmp_path / "project" / "deep" / "Reuniao 2026.wav")

    assert sources.find(ref, roots=[str(tmp_path / "project")]) == moved


def test_find_survives_a_missing_root(tmp_path):
    ref = sources.reference(_write(tmp_path / "mic.wav"))

    assert sources.find(ref, roots=[str(tmp_path / "unmounted")]) is None


def test_find_walks_only_as_deep_as_the_search_depth(tmp_path):
    original = _write(tmp_path / "inbox" / "mic.wav")
    ref = sources.reference(original, path=str(original))
    original.unlink()
    root = tmp_path / "projects"
    directly = _write(root / "direct.wav")
    deep = _write(root / "a" / "b" / "c" / "d" / "file.wav")  # depth 4
    roots = [str(root)]

    assert sources.find(ref, roots) == directly  # depth 0 counts
    directly.unlink()
    assert sources.find(ref, roots) is None  # default depth 3 stops above depth 4
    assert sources.find(ref, roots, depth=3) is None
    assert sources.find(ref, roots, depth=4) == deep


def test_depth_three_reaches_the_briefing_folder_of_a_terrain(tmp_path):
    original = _write(tmp_path / "inbox" / "mic.wav")
    ref = sources.reference(original, path=str(original))
    original.unlink()
    moved = _write(tmp_path / "root" / "Bauru" / "Terreno 1" / "5-BRIEFING" / "mic.wav")

    assert sources.find(ref, [str(tmp_path / "root")]) == moved
    assert sources.find(ref, [str(tmp_path / "root")], depth=2) is None
