"""AudioService: dual-track extraction, stereo splitting, and probing.

ffmpeg/ffprobe are external, so these tests mock subprocess.run and verify the
command construction and the probe parsing logic.
"""

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

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


def test_probe_audio_stereo_single_stream():
    stdout = json.dumps({
        "streams": [
            {"codec": "pcm_s16le", "channels": 2, "index": 0},
        ]
    })
    with patch("subprocess.run", side_effect=_fake_run(stdout)[0]):
        probe = AudioService().probe_audio("stereo.wav")

    assert probe["stream_count"] == 1
    assert probe["channels"] == 2
    assert probe["streams"] == [{"index": 0, "channels": 2}]


def test_probe_audio_multi_stream_two_mono():
    stdout = json.dumps({
        "streams": [
            {"codec": "aac", "channels": 1, "index": 0},
            {"codec": "aac", "channels": 1, "index": 1},
        ]
    })
    with patch("subprocess.run", side_effect=_fake_run(stdout)[0]):
        probe = AudioService().probe_audio("multi.wav")

    assert probe["stream_count"] == 2
    assert probe["channels"] == 1
    assert probe["streams"] == [{"index": 0, "channels": 1}, {"index": 1, "channels": 1}]


def test_probe_audio_single_mono():
    stdout = json.dumps({
        "streams": [
            {"codec": "mp3", "channels": 1, "index": 0},
        ]
    })
    with patch("subprocess.run", side_effect=_fake_run(stdout)[0]):
        probe = AudioService().probe_audio("mono.mp3")

    assert probe["stream_count"] == 1
    assert probe["channels"] == 1


def test_probe_audio_no_audio_streams_defaults_to_mono():
    stdout = json.dumps({"streams": [{"codec": "h264", "index": 0}]})
    with patch("subprocess.run", side_effect=_fake_run(stdout)[0]):
        probe = AudioService().probe_audio("video.mp4")

    assert probe["stream_count"] == 0
    assert probe["channels"] == 1


def test_extract_dual_audio_splits_stereo_when_same_file():
    # Probe reports a single stereo stream (1 stream, 2 channels).
    probe = json.dumps({"streams": [{"codec": "pcm_s16le", "channels": 2, "index": 0}]})
    run, calls = _fake_run(probe_stdout=probe)
    with patch("subprocess.run", side_effect=run):
        out = AudioService().extract_dual_audio("same.wav", "same.wav", "m1")

    # 4 calls: probe (ffprobe), split mic, split system, mix.
    assert len(calls) == 4
    # The split commands use the pan filter to extract channel 0 and channel 1.
    assert any("pan=mono|c0=1:c1=0" in c for c in calls[1])
    assert any("pan=mono|c0=0:c1=1" in c for c in calls[2])
    # The mix uses amix with normalize.
    assert any("amix=inputs=2:normalize=1" in c for c in calls[3])
    # Output is the mixed audio.wav.
    assert out.endswith("audio.wav")


def test_extract_dual_audio_splits_multi_stream_when_same_file():
    # Probe reports two mono streams (OBS-style multi-stream).
    probe = json.dumps({"streams": [
        {"codec": "aac", "channels": 1, "index": 0},
        {"codec": "aac", "channels": 1, "index": 1},
    ]})
    run, calls = _fake_run(probe_stdout=probe)
    with patch("subprocess.run", side_effect=run):
        out = AudioService().extract_dual_audio("same.wav", "same.wav", "m1")

    # 4 calls: probe (ffprobe), split mic, split system, mix.
    assert len(calls) == 4
    # The split commands map stream 0 and stream 1.
    assert "-map" in calls[1] and "0:a:0" in calls[1]
    assert "-map" in calls[2] and "0:a:1" in calls[2]
    assert out.endswith("audio.wav")


def test_extract_dual_audio_extracts_separate_files_when_different():
    run, calls = _fake_run()
    with patch("subprocess.run", side_effect=run):
        out = AudioService().extract_dual_audio("mic.wav", "system.wav", "m1")

    # 3 ffmpeg calls: extract mic, extract system, mix (no probe for separate files).
    assert len(calls) == 3
    # No -map channel splitting for separate files.
    assert not any("-map" in c for c in calls[:2])
    # Both inputs are present in the mix command (as full paths).
    assert any("mic.wav" in x for x in calls[2])
    assert any("system.wav" in x for x in calls[2])
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
