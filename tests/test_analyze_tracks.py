"""AudioService.analyze_tracks against real ffmpeg on generated files.

The risk here is the ffmpeg command text (stream mapping, pan, windows), which a mocked
subprocess cannot check, so these run real ffmpeg/ffprobe over files made with lavfi.
Independent noise stands in for different voices.
"""

import shutil
import subprocess

import pytest

from services.audio_service import AudioService

pytestmark = pytest.mark.skipif(
    not (shutil.which("ffmpeg") and shutil.which("ffprobe")), reason="ffmpeg is not installed"
)

RATE = 16000


def noise(seed: int, seconds: float, amplitude: float = 0.2) -> str:
    return f"anoisesrc=d={seconds}:seed={seed}:amplitude={amplitude}:sample_rate={RATE}"


def make(path, inputs: list[str], *options: str) -> str:
    cmd = ["ffmpeg", "-v", "error", "-y"]
    for source in inputs:
        cmd += ["-f", "lavfi", "-i", source]
    subprocess.run([*cmd, *options, str(path)], check=True, capture_output=True)
    return str(path)


def statuses(layout):
    return [t["status"] for t in layout["tracks"]]


def test_obs_file_with_a_mix_on_track_one_uses_tracks_two_and_three(tmp_path):
    path = make(
        tmp_path / "obs.mkv", [noise(1, 20), noise(2, 20)],
        "-filter_complex", "[0][1]amix=inputs=2:normalize=0[m]",
        "-map", "[m]", "-map", "0:a", "-map", "1:a", "-c:a", "pcm_s16le",
    )

    layout = AudioService().analyze_tracks(path)

    assert statuses(layout) == ["mix", "speech", "speech"]
    assert layout["mic"] == {"stream": 1, "channel": None}
    assert layout["system"] == {"stream": 2, "channel": None}
    assert layout["audio"] is None
    assert layout["manual"] is False


def test_the_mix_is_found_after_a_lossy_codec_too(tmp_path):
    path = make(
        tmp_path / "obs.mp4", [noise(1, 20), noise(2, 20)],
        "-filter_complex", "[0][1]amix=inputs=2:normalize=0[m]",
        "-map", "[m]", "-map", "0:a", "-map", "1:a", "-c:a", "aac", "-b:a", "128k",
    )

    assert statuses(AudioService().analyze_tracks(path)) == ["mix", "speech", "speech"]


def test_two_streams_are_the_mic_and_the_system_even_when_each_is_stereo(tmp_path):
    """OBS's own profile: two AAC streams, each stereo."""
    path = make(
        tmp_path / "obs.mp4", [noise(1, 20), noise(2, 20)],
        "-filter_complex", "[0]aformat=channel_layouts=stereo[a];[1]aformat=channel_layouts=stereo[b]",
        "-map", "[a]", "-map", "[b]", "-c:a", "aac",
    )

    layout = AudioService().analyze_tracks(path)

    assert statuses(layout) == ["speech", "speech"]
    assert layout["mic"] == {"stream": 0, "channel": None}
    assert layout["system"] == {"stream": 1, "channel": None}


def test_a_real_stereo_file_is_a_mic_on_the_left_and_a_system_on_the_right(tmp_path):
    path = make(
        tmp_path / "st.wav", [noise(1, 20), noise(2, 20)],
        "-filter_complex", "[0][1]join=inputs=2:channel_layout=stereo",
    )

    layout = AudioService().analyze_tracks(path)

    assert statuses(layout) == ["speech", "speech"]
    assert layout["mic"] == {"stream": 0, "channel": 0}
    assert layout["system"] == {"stream": 0, "channel": 1}


def test_a_stereo_file_with_identical_channels_is_one_track(tmp_path):
    path = make(
        tmp_path / "fake.wav", [noise(1, 20)],
        "-filter_complex", "[0]asplit[a][b];[a][b]join=inputs=2:channel_layout=stereo",
    )

    layout = AudioService().analyze_tracks(path)

    assert statuses(layout) == ["speech", "duplicate"]
    assert layout["mic"] is None and layout["system"] is None
    assert layout["audio"] == {"stream": 0, "channel": 0}


def test_a_silent_system_track_leaves_a_single_file_read_from_the_mic(tmp_path):
    path = make(
        tmp_path / "quiet.mkv", [noise(1, 20), "anullsrc=r=16000:cl=mono:d=20"],
        "-map", "0:a", "-map", "1:a", "-c:a", "pcm_s16le",
    )

    layout = AudioService().analyze_tracks(path)

    assert statuses(layout) == ["speech", "silent"]
    assert layout["system"] is None
    assert layout["audio"] == {"stream": 0, "channel": None}


def test_a_system_track_that_speaks_only_between_the_sampled_windows_is_not_silent(tmp_path):
    """The windows sample 10%, 50% and 90% of a long file; remote talk in between must count."""
    path = make(
        tmp_path / "long.mkv",
        [noise(1, 400), noise(2, 400, amplitude=0.0001), noise(3, 30)],
        "-filter_complex",
        # System: near-silence, with 30 s of noise from second 100 to 130 (outside every window).
        "[2]adelay=100000:all=1,apad=whole_dur=400[burst];[1][burst]amix=inputs=2:normalize=0[sys]",
        "-map", "0:a", "-map", "[sys]", "-t", "400", "-c:a", "pcm_s16le",
    )

    layout = AudioService().analyze_tracks(path)

    assert statuses(layout) == ["speech", "speech"]
    assert layout["system"] == {"stream": 1, "channel": None}


def test_tracks_named_in_portuguese_with_accents_are_read_and_decide_the_roles(tmp_path):
    """OBS names its tracks "Computador" and "Microfone"; a title or a file name with an
    accent must not break ffprobe's output on a Windows code page (byte 0x81 in cp1252)."""
    path = make(
        tmp_path / "GRAVAÇÃO - ligação.mkv", [noise(1, 20), noise(2, 20)],
        "-map", "0:a", "-map", "1:a", "-c:a", "pcm_s16le",
        "-metadata:s:a:0", "title=Áudio do Computador", "-metadata:s:a:1", "title=Microfone",
        "-metadata", "title=GRAVAÇÃO",
    )
    service = AudioService()

    assert service.get_duration(path) == pytest.approx(20, abs=0.5)
    layout = service.analyze_tracks(path)

    assert [t["title"] for t in layout["tracks"]] == ["Áudio do Computador", "Microfone"]
    assert layout["mic"] == {"stream": 1, "channel": None}
    assert layout["system"] == {"stream": 0, "channel": None}


def test_a_video_stream_does_not_shift_the_audio_numbering(tmp_path):
    path = make(
        tmp_path / "obs.mkv", ["color=c=black:s=64x64:d=20:r=5", noise(1, 20), noise(2, 20)],
        "-map", "0:v", "-map", "1:a", "-map", "2:a", "-c:v", "mpeg4", "-c:a", "pcm_s16le",
    )

    layout = AudioService().analyze_tracks(path)

    assert layout["mic"] == {"stream": 0, "channel": None}
    assert layout["system"] == {"stream": 1, "channel": None}


def test_the_extracted_tracks_are_the_ones_the_layout_names(tmp_path, monkeypatch):
    """End to end: the mic track of an OBS file holds the mic's noise, not the mix's."""
    import config

    monkeypatch.setattr(config.settings, "storage_path", str(tmp_path / "storage"))
    path = make(
        tmp_path / "obs.mkv", [noise(1, 20), noise(2, 20)],
        "-filter_complex", "[0][1]amix=inputs=2:normalize=0[m]",
        "-map", "[m]", "-map", "0:a", "-map", "1:a", "-c:a", "pcm_s16le",
    )
    service = AudioService()
    layout = service.analyze_tracks(path)

    mic_out, system_out = service.extract_dual_tracks(path, path, "m1", layout)

    assert service.get_duration(mic_out) == pytest.approx(20, abs=0.5)
    assert service.get_duration(system_out) == pytest.approx(20, abs=0.5)
