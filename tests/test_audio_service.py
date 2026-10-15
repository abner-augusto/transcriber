"""AudioService: dual-track extraction, stereo splitting, and probing.

ffmpeg/ffprobe are external, so these tests mock subprocess.run and verify the
command construction and the probe parsing logic.
"""

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from services.audio_service import AudioService


def _fake_run(probe_stdout: str = ""):
    """A subprocess.run stand-in that records calls.

    Returns a fixed result. For ffprobe commands it returns ``probe_stdout`` (so
    probe_audio can parse it); for ffmpeg commands it returns empty.
    """
    calls: list[list[str]] = []

    def run(cmd, **kwargs):
        calls.append(cmd)
        is_ffprobe = any("ffprobe" in c for c in cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout=probe_stdout if is_ffprobe else "")

    return run, calls


def _ffprobe(*streams: dict) -> str:
    """What `ffprobe -print_format json -show_streams` prints: `codec_name` and `codec_type`
    on every stream, `channels` only on audio (captured from ffmpeg 2026-10-15)."""
    return json.dumps({"streams": list(streams)})


def _audio(index: int, channels: int, codec: str = "aac", title: str | None = None) -> dict:
    stream = {"index": index, "codec_name": codec, "codec_type": "audio", "channels": channels}
    if title:
        stream["tags"] = {"title": title}
    return stream


VIDEO = {"index": 0, "codec_name": "h264", "codec_type": "video", "width": 1920, "height": 1080}


def test_probe_audio_stereo_single_stream():
    stdout = _ffprobe(_audio(0, 2, "pcm_s16le"))
    with patch("subprocess.run", side_effect=_fake_run(stdout)[0]):
        probe = AudioService().probe_audio("stereo.wav")

    assert probe["stream_count"] == 1
    assert probe["channels"] == 2
    assert probe["streams"] == [{"stream": 0, "channels": 2, "title": None}]


def test_probe_audio_multi_stream_two_mono():
    stdout = _ffprobe(_audio(0, 1), _audio(1, 1))
    with patch("subprocess.run", side_effect=_fake_run(stdout)[0]):
        probe = AudioService().probe_audio("multi.mkv")

    assert probe["stream_count"] == 2
    assert probe["channels"] == 1
    assert probe["streams"] == [
        {"stream": 0, "channels": 1, "title": None},
        {"stream": 1, "channels": 1, "title": None},
    ]


def test_probe_audio_numbers_audio_streams_apart_from_the_video_stream():
    """`-map 0:a:N` counts audio streams only: an OBS .mkv has the video first."""
    stdout = _ffprobe(VIDEO, _audio(1, 1, title="Mic"), _audio(2, 1, title="Desktop"))
    with patch("subprocess.run", side_effect=_fake_run(stdout)[0]):
        probe = AudioService().probe_audio("obs.mkv")

    assert probe["stream_count"] == 2
    assert probe["streams"] == [
        {"stream": 0, "channels": 1, "title": "Mic"},
        {"stream": 1, "channels": 1, "title": "Desktop"},
    ]


def test_probe_audio_single_mono():
    stdout = _ffprobe(_audio(0, 1, "mp3"))
    with patch("subprocess.run", side_effect=_fake_run(stdout)[0]):
        probe = AudioService().probe_audio("mono.mp3")

    assert probe["stream_count"] == 1
    assert probe["channels"] == 1


def test_probe_audio_no_audio_streams_defaults_to_mono():
    stdout = _ffprobe(VIDEO)
    with patch("subprocess.run", side_effect=_fake_run(stdout)[0]):
        probe = AudioService().probe_audio("video.mp4")

    assert probe["stream_count"] == 0
    assert probe["channels"] == 1


def _after(cmd: list[str], flag: str) -> str:
    return cmd[cmd.index(flag) + 1]


def test_extract_dual_audio_splits_stereo_channels_by_the_layout():
    layout = {
        "mic": {"stream": 0, "channel": 0},
        "system": {"stream": 0, "channel": 1},
    }
    run, calls = _fake_run()
    with patch("subprocess.run", side_effect=run):
        out = AudioService().extract_dual_audio("same.wav", "same.wav", "m1", layout=layout)

    # 3 calls, no probe: split mic, split system, mix.
    assert len(calls) == 3
    assert _after(calls[0], "-map") == "0:a:0" and "pan=mono|c0=c0" in _after(calls[0], "-af")
    assert _after(calls[1], "-map") == "0:a:0" and "pan=mono|c0=c1" in _after(calls[1], "-af")
    assert all("loudnorm" in _after(c, "-af") for c in calls[:2])
    assert "amix=inputs=2:normalize=1" in _after(calls[2], "-filter_complex")
    assert out.endswith("audio.wav")


def test_extract_dual_audio_maps_the_streams_the_layout_names():
    """An OBS file with a mix on track 1: the mic and the system are tracks 2 and 3."""
    layout = {
        "mic": {"stream": 1, "channel": None},
        "system": {"stream": 2, "channel": None},
    }
    run, calls = _fake_run()
    with patch("subprocess.run", side_effect=run):
        AudioService().extract_dual_audio("obs.mkv", "obs.mkv", "m1", layout=layout)

    assert [_after(c, "-map") for c in calls[:2]] == ["0:a:1", "0:a:2"]
    # Each stream is one track: a stereo stream is mixed down, not split.
    assert not any("pan=" in _after(c, "-af") for c in calls[:2])
    assert all(_after(c, "-ac") == "1" for c in calls[:2])


def test_extract_dual_audio_without_a_layout_falls_back_to_the_first_two_streams():
    """A Meeting made with the same file as mic and system, before layouts existed."""
    probe = _ffprobe(_audio(0, 1), _audio(1, 1))
    run, calls = _fake_run(probe_stdout=probe)
    with patch("subprocess.run", side_effect=run):
        AudioService().extract_dual_audio("same.mkv", "same.mkv", "m1")

    assert len(calls) == 4  # probe, mic, system, mix
    assert [_after(c, "-map") for c in calls[1:3]] == ["0:a:0", "0:a:1"]


def test_extract_dual_audio_without_a_layout_falls_back_to_the_two_channels_of_a_stereo_file():
    probe = _ffprobe(_audio(0, 2, "pcm_s16le"))
    run, calls = _fake_run(probe_stdout=probe)
    with patch("subprocess.run", side_effect=run):
        AudioService().extract_dual_audio("same.wav", "same.wav", "m1")

    assert "pan=mono|c0=c0" in _after(calls[1], "-af")
    assert "pan=mono|c0=c1" in _after(calls[2], "-af")


def test_extract_audio_reads_the_one_track_the_layout_picked():
    run, calls = _fake_run()
    with patch("subprocess.run", side_effect=run):
        AudioService().extract_audio("obs.mkv", "m1", track={"stream": 1, "channel": None})

    assert _after(calls[0], "-map") == "0:a:1"
    assert _after(calls[0], "-ac") == "1"


def test_extract_dual_audio_extracts_separate_files_when_different():
    run, calls = _fake_run()
    with patch("subprocess.run", side_effect=run):
        out = AudioService().extract_dual_audio("mic.wav", "system.wav", "m1")

    # 3 ffmpeg calls: extract mic, extract system, mix (no probe for separate files).
    assert len(calls) == 3
    # No -map channel splitting for separate files.
    assert not any("-map" in c for c in calls[:2])
    # Both processed inputs are present in the mix command (as full paths).
    assert any("mic_processed.wav" in x for x in calls[2])
    assert any("system_processed.wav" in x for x in calls[2])
    assert out.endswith("audio.wav")


def test_extract_dual_audio_uses_16k_mono_loudnorm():
    run, calls = _fake_run()
    with patch("subprocess.run", side_effect=run):
        AudioService().extract_dual_audio("mic.wav", "system.wav", "m1")

    for c in calls[:2]:
        assert "-ar" in c and "16000" in c
        assert "-ac" in c and "1" in c
        assert any("loudnorm" in x for x in c)


def test_extract_dual_audio_output_paths_are_in_meeting_dir():
    run, calls = _fake_run()
    with patch("subprocess.run", side_effect=run):
        out = AudioService().extract_dual_audio("mic.wav", "system.wav", "m1")

    # The mixed output lives in the meeting's storage directory.
    assert Path(out).name == "audio.wav"
    assert "m1" in out


def test_extract_dual_audio_never_overwrites_source_artifacts(tmp_path):
    """Legacy dual-track rows may point at mic.wav/system.wav source files."""
    meeting_dir = tmp_path / "m1"
    meeting_dir.mkdir()
    run, calls = _fake_run()

    with patch("services.audio_service.get_meeting_path", return_value=meeting_dir):
        with patch("subprocess.run", side_effect=run):
            AudioService().extract_dual_audio(
                str(meeting_dir / "mic.wav"),
                str(meeting_dir / "system.wav"),
                "m1",
            )

    assert calls[0][-1] == str(meeting_dir / "mic_processed.wav")
    assert calls[1][-1] == str(meeting_dir / "system_processed.wav")


def test_ffmpeg_failure_preserves_stderr(monkeypatch, tmp_path):
    import config

    monkeypatch.setattr(config.settings, "storage_path", str(tmp_path))
    expected_stderr = "Output same as Input - exiting"
    failure = subprocess.CalledProcessError(
        returncode=4294967274,
        cmd=["ffmpeg", "-i", "input.wav", "output.wav"],
        stderr=expected_stderr,
    )

    with patch("subprocess.run", side_effect=failure):
        with pytest.raises(RuntimeError, match=expected_stderr):
            AudioService().extract_audio("input.wav", "meeting-1")


def test_extract_dual_tracks_makes_only_the_two_processed_tracks_and_never_writes_to_the_inputs():
    run, calls = _fake_run()
    with patch("subprocess.run", side_effect=run):
        mic_out, system_out = AudioService().extract_dual_tracks("D:/p/mic.wav", "D:/p/system.wav", "m1")

    assert [Path(mic_out).name, Path(system_out).name] == ["mic_processed.wav", "system_processed.wav"]
    assert len(calls) == 2  # no mix: audio.wav is already kept
    assert [c[-1] for c in calls] == [mic_out, system_out]  # ffmpeg writes only to the Meeting folder
    assert [c[c.index("-i") + 1] for c in calls] == ["D:/p/mic.wav", "D:/p/system.wav"]
