"""After processing the app keeps only the derived audio; the originals live elsewhere."""

from types import SimpleNamespace

import config
from services import audio_retention


def _meeting_dir(monkeypatch, tmp_path, meeting_id="m1"):
    monkeypatch.setattr(config.settings, "storage_path", str(tmp_path / "storage"))
    directory = config.get_meeting_path(meeting_id)
    return directory


def _write(directory, *names):
    for name in names:
        (directory / name).write_bytes(b"RIFF")


def _meeting(directory, **columns):
    values = {
        "id": directory.name,
        "audio_filepath": str(directory / "audio.wav"),
        "mic_audio_filepath": None,
        "system_audio_filepath": None,
    }
    values.update(columns)
    return SimpleNamespace(**values)


def test_dual_track_sources_and_processed_tracks_go_and_the_mix_stays(monkeypatch, tmp_path):
    directory = _meeting_dir(monkeypatch, tmp_path)
    _write(
        directory, "mic_source.wav", "system_source.wav", "mic_processed.wav",
        "system_processed.wav", "audio.wav", "audio.wav.json",
    )
    meeting = _meeting(
        directory,
        mic_audio_filepath=str(directory / "mic_source.wav"),
        system_audio_filepath=str(directory / "system_source.wav"),
    )

    audio_retention.drop_raw_audio(meeting)

    assert sorted(p.name for p in directory.iterdir()) == ["audio.wav", "audio.wav.json"]
    assert meeting.mic_audio_filepath is None
    assert meeting.system_audio_filepath is None
    assert meeting.audio_filepath == str(directory / "audio.wav")


def test_single_track_original_of_any_container_goes(monkeypatch, tmp_path):
    directory = _meeting_dir(monkeypatch, tmp_path)
    _write(directory, "original.mov", "original.mp4", "original.wav", "audio.wav")

    audio_retention.drop_raw_audio(_meeting(directory))

    assert [p.name for p in directory.iterdir()] == ["audio.wav"]


def test_a_stereo_original_shared_by_both_paths_goes_once(monkeypatch, tmp_path):
    directory = _meeting_dir(monkeypatch, tmp_path)
    _write(directory, "original.mov", "mic_processed.wav", "system_processed.wav", "audio.wav")
    shared = str(directory / "original.mov")
    meeting = _meeting(directory, mic_audio_filepath=shared, system_audio_filepath=shared)

    audio_retention.drop_raw_audio(meeting)

    assert [p.name for p in directory.iterdir()] == ["audio.wav"]
    assert (meeting.mic_audio_filepath, meeting.system_audio_filepath) == (None, None)


def test_never_deletes_the_file_the_meeting_plays(monkeypatch, tmp_path):
    directory = _meeting_dir(monkeypatch, tmp_path)
    _write(directory, "original.wav")

    audio_retention.drop_raw_audio(_meeting(directory, audio_filepath=str(directory / "original.wav")))

    assert (directory / "original.wav").exists()


def test_nothing_outside_the_meeting_folder_is_touched(monkeypatch, tmp_path):
    directory = _meeting_dir(monkeypatch, tmp_path)
    outside = tmp_path / "project-folder"
    outside.mkdir()
    (outside / "mic_source.wav").write_bytes(b"RIFF")
    _write(directory, "audio.wav", "notes.txt")
    meeting = _meeting(directory, mic_audio_filepath=str(outside / "mic_source.wav"))

    audio_retention.drop_raw_audio(meeting)

    assert (outside / "mic_source.wav").exists()
    assert (directory / "notes.txt").exists()
    assert meeting.mic_audio_filepath is None


def test_missing_files_and_an_undeletable_file_do_not_stop_the_step(monkeypatch, tmp_path):
    directory = _meeting_dir(monkeypatch, tmp_path)
    _write(directory, "mic_source.wav", "system_source.wav", "audio.wav")
    real_unlink = type(directory).unlink

    def unlink(self, *args, **kwargs):
        if self.name == "mic_source.wav":
            raise PermissionError("locked")
        return real_unlink(self, *args, **kwargs)

    monkeypatch.setattr(type(directory), "unlink", unlink)
    meeting = _meeting(
        directory,
        mic_audio_filepath=str(directory / "mic_source.wav"),
        system_audio_filepath=str(directory / "system_source.wav"),
    )

    audio_retention.drop_raw_audio(meeting)

    assert sorted(p.name for p in directory.iterdir()) == ["audio.wav", "mic_source.wav"]
    assert (meeting.mic_audio_filepath, meeting.system_audio_filepath) == (None, None)
