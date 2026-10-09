"""The command-line client, exercised end to end through the FastAPI TestClient."""

import json

import pytest
from fastapi.testclient import TestClient

from main import app
from models import Meeting, MeetingStatus, Segment, Speaker, VocabularyEntry
from models.job import Job, JobStatus, JobType
from transcriber_cli.client import Api, ApiError, connection_failure
from transcriber_cli.main import main
from transcriber_cli.render import clock, parse_clock


def forward_to_app(client):
    def transport(method, url, headers, body):
        path = url.split("://", 1)[1].split("/", 1)[1]
        content = body if isinstance(body, (bytes, type(None))) else b"".join(body)
        r = client.request(method, "/" + path, content=content, headers=headers)
        return r.status_code, r.content

    return transport


@pytest.fixture
def api(db_session):
    return Api(base_url="http://test", transport=forward_to_app(TestClient(app)))


def seed_meeting(db, *, id=None, title="Obra 12", status=MeetingStatus.COMPLETED):
    meeting = Meeting(title=title, status=status, duration=3725.0)
    if id:
        meeting.id = id
    db.add(meeting)
    db.flush()
    return meeting


def add_speaker(db, meeting, label, name=None, identified_by=None, **kw):
    speaker = Speaker(
        meeting_id=meeting.id, label=label, display_name=name,
        identified_by=identified_by, **kw,
    )
    db.add(speaker)
    db.flush()
    return speaker


def add_segment(db, meeting, speaker, order, start, end, text, **kw):
    segment = Segment(
        meeting_id=meeting.id, speaker_id=speaker.id if speaker else None,
        order=order, start_time=start, end_time=end, text=text, **kw,
    )
    db.add(segment)
    db.flush()
    return segment


def run(argv, api, capsys):
    code = main(argv, api=api)
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_list_prints_short_id_and_title(db_session, api, capsys):
    meeting = seed_meeting(db_session, title="Obra 12")
    db_session.commit()

    code, out, _ = run(["list"], api, capsys)

    assert code == 0
    assert meeting.id[:8] in out
    assert "Obra 12" in out
    assert meeting.id not in out


def test_meeting_handle_resolves_unique_prefix_and_rejects_ambiguous(db_session, api, capsys):
    seed_meeting(db_session, id="abcd1111-0000", title="Primeira")
    seed_meeting(db_session, id="abcd2222-0000", title="Segunda")
    db_session.commit()

    code, out, _ = run(["show", "abcd11"], api, capsys)
    assert code == 0
    assert "Primeira" in out

    code, out, err = run(["show", "abcd"], api, capsys)
    assert code == 1
    assert "matches 2 Meetings" in err
    assert out == ""


def test_meeting_handle_resolves_title_and_reports_unknown(db_session, api, capsys):
    seed_meeting(db_session, title="Reuniao Final")
    db_session.commit()

    code, out, _ = run(["show", "reuniao final"], api, capsys)
    assert code == 0
    assert "Reuniao Final" in out

    code, _, err = run(["show", "nothing-like-it"], api, capsys)
    assert code == 1
    assert "No Meeting matches 'nothing-like-it'" in err


def test_show_renders_segment_lines_with_markers(db_session, api, capsys):
    meeting = seed_meeting(db_session)
    maria = add_speaker(db_session, meeting, "SPEAKER_00", "Maria")
    add_segment(db_session, meeting, maria, 0, 0.0, 4.0, "Bom dia", confidence=0.41)
    add_segment(
        db_session, meeting, maria, 1, 5.0, 8.0, "Garrah chegou",
        is_edited=True, speaker_edited=True, confidence=0.9,
        corrections=[{"start": 5.0, "end": 5.4, "heard": " Galo", "term": "Garrah", "rule": "x"}],
    )
    db_session.commit()

    code, out, _ = run(["show", meeting.id], api, capsys)

    assert code == 0
    assert "#0 00:00 Maria: Bom dia [conf 0.41]" in out
    assert "#1 00:05 Maria: Garrah chegou [edited] [moved] [fixed: Galo->Garrah]" in out
    assert meeting.id in out


def test_show_time_range_and_speaker_filters(db_session, api, capsys):
    meeting = seed_meeting(db_session)
    ana = add_speaker(db_session, meeting, "SPEAKER_00", "Ana")
    bruno = add_speaker(db_session, meeting, "SPEAKER_01", "Bruno")
    add_segment(db_session, meeting, ana, 0, 0.0, 30.0, "inicio")
    add_segment(db_session, meeting, bruno, 1, 70.0, 90.0, "meio")
    add_segment(db_session, meeting, ana, 2, 200.0, 220.0, "fim")
    db_session.commit()

    _, out, _ = run(["show", meeting.id, "--from", "1:00", "--to", "2:00"], api, capsys)
    assert "meio" in out
    assert "inicio" not in out and "fim" not in out

    _, out, _ = run(["show", meeting.id, "--speaker", "Ana"], api, capsys)
    assert "inicio" in out and "fim" in out
    assert "meio" not in out

    _, out, _ = run(["show", meeting.id, "--limit", "1"], api, capsys)
    assert "inicio" in out
    assert "meio" not in out


def seed_grep_meeting(db):
    meeting = seed_meeting(db)
    meeting.vocabulary = "Garrah, Habite-se"
    ana = add_speaker(db, meeting, "SPEAKER_00", "Ana")
    bruno = add_speaker(db, meeting, "SPEAKER_01", "Bruno")
    add_segment(db, meeting, ana, 0, 0.0, 30.0, "Falou com a LOURDES ontem")
    add_segment(db, meeting, bruno, 1, 70.0, 90.0, "A Lourdes confirmou")
    add_segment(db, meeting, ana, 2, 200.0, 220.0, "Nada a ver")
    db.commit()
    return meeting


def test_show_range_prints_only_segments(db_session, api, capsys):
    meeting = seed_grep_meeting(db_session)

    _, out, _ = run(["show", meeting.id, "--from", "1:00", "--to", "2:00"], api, capsys)

    assert "Lourdes confirmou" in out
    assert "vocabulary:" not in out
    assert "SPEAKER_00" not in out and meeting.id not in out


def test_show_grep_filters_segments(db_session, api, capsys):
    meeting = seed_grep_meeting(db_session)

    _, out, _ = run(["show", meeting.id, "--grep", "lourdes"], api, capsys)
    assert "LOURDES ontem" in out and "Lourdes confirmou" in out
    assert "Nada a ver" not in out

    _, out, _ = run(["show", meeting.id, "--grep", "lourdes", "--speaker", "Bruno"], api, capsys)
    assert "Lourdes confirmou" in out
    assert "LOURDES ontem" not in out


def test_show_grep_rejects_an_invalid_pattern(db_session, api, capsys):
    meeting = seed_grep_meeting(db_session)

    code, _, err = run(["show", meeting.id, "--grep", "(unclosed"], api, capsys)

    assert code == 1
    assert "invalid --grep pattern" in err


def test_show_without_filters_keeps_header(db_session, api, capsys):
    meeting = seed_grep_meeting(db_session)

    _, out, _ = run(["show", meeting.id], api, capsys)

    assert meeting.id in out
    assert "vocabulary:" in out
    assert "SPEAKER_00" in out
    assert "Nada a ver" in out


def test_speakers_unnamed_lists_unidentified_with_longest_samples(db_session, api, capsys):
    meeting = seed_meeting(db_session)
    anon = add_speaker(db_session, meeting, "SPEAKER_00", None, None, segment_count=5, total_speaking_time=70.0)
    known = add_speaker(db_session, meeting, "SPEAKER_01", "Carla", "voice_profile", segment_count=1)
    unknown = add_speaker(db_session, meeting, "UNKNOWN", None, None)
    for order, (start, end) in enumerate([(0, 1), (2, 12), (13, 15), (16, 36), (40, 45)]):
        add_segment(db_session, meeting, anon, order, start, end, f"fala {order}")
    add_segment(db_session, meeting, known, 9, 50.0, 52.0, "carla fala")
    add_segment(db_session, meeting, unknown, 10, 60.0, 61.0, "ruido")
    db_session.commit()

    code, out, _ = run(["speakers", meeting.id, "--unnamed"], api, capsys)

    assert code == 0
    assert 'SPEAKER_00 "" by=- segs=5 time=01:10' in out
    assert "SPEAKER_01" not in out
    assert "UNKNOWN" not in out
    samples = [line for line in out.splitlines() if line.startswith("  #")]
    assert len(samples) == 3
    assert "fala 3" in samples[0] and "fala 1" in samples[1] and "fala 4" in samples[2]


def test_speakers_unnamed_lists_a_default_host(db_session, api, capsys):
    meeting = seed_meeting(db_session)
    add_speaker(db_session, meeting, "HOST", "You", "host_track")
    add_speaker(db_session, meeting, "SPEAKER_00", "Carla", "voice_profile")
    add_speaker(db_session, meeting, "SPEAKER_01", "Ana", "manual")
    db_session.commit()

    code, out, _ = run(["speakers", meeting.id, "--unnamed"], api, capsys)

    assert code == 0
    assert "HOST" in out
    assert "SPEAKER_00" not in out and "SPEAKER_01" not in out


def test_speakers_without_filter_lists_everyone(db_session, api, capsys):
    meeting = seed_meeting(db_session)
    add_speaker(db_session, meeting, "SPEAKER_00", "Ana", "manual")
    add_speaker(db_session, meeting, "SPEAKER_01", None, None)
    db_session.commit()

    _, out, _ = run(["speakers", meeting.id], api, capsys)

    assert 'SPEAKER_00 "Ana" by=manual' in out
    assert "SPEAKER_01" in out


def test_upload_sends_multipart_and_creates_the_meeting(db_session, api, capsys, tmp_path, monkeypatch):
    monkeypatch.setattr("config.settings.storage_path", str(tmp_path / "storage"))
    monkeypatch.setattr(
        "api.meetings.AudioService.probe_audio",
        lambda self, path: {"stream_count": 1, "channels": 1},
    )
    audio = tmp_path / "reuniao.wav"
    audio.write_bytes(b"0123456789")

    code, out, _ = run(
        ["upload", str(audio), "--title", "Obra 12/10", "--participants", "Ana, Bruno",
         "--vocabulary", "Garrah", "--min-speakers", "2"],
        api, capsys,
    )

    assert code == 0
    meeting = db_session.query(Meeting).one()
    assert meeting.id in out
    assert meeting.title == "Obra 12/10"
    assert meeting.participants == "Ana, Bruno"
    assert meeting.vocabulary == "Garrah"
    assert meeting.min_speakers == 2
    saved = tmp_path / "storage" / meeting.id / "original.wav"
    assert saved.read_bytes() == b"0123456789"


def test_wait_exit_codes_follow_the_newest_job(db_session, api, capsys):
    done = seed_meeting(db_session, title="ok")
    failed = seed_meeting(db_session, title="bad")
    db_session.add(Job(meeting_id=done.id, job_type=JobType.PROCESS_MEETING,
                       status=JobStatus.COMPLETED, progress=100.0, current_step="Done"))
    db_session.add(Job(meeting_id=failed.id, job_type=JobType.PROCESS_MEETING,
                       status=JobStatus.FAILED, progress=40.0, error="GPU out of memory"))
    db_session.commit()

    code, _, _ = run(["wait", done.id, "--interval", "0"], api, capsys)
    assert code == 0

    code, out, err = run(["wait", failed.id, "--interval", "0"], api, capsys)
    assert code == 1
    assert "GPU out of memory" in out + err


def test_wait_times_out_with_exit_3(db_session, api, capsys):
    meeting = seed_meeting(db_session, status=MeetingStatus.PROCESSING)
    db_session.add(Job(meeting_id=meeting.id, job_type=JobType.PROCESS_MEETING,
                       status=JobStatus.RUNNING, progress=10.0, current_step="Transcribing"))
    db_session.commit()

    code, out, _ = run(["wait", meeting.id, "--interval", "0", "--timeout", "0"], api, capsys)

    assert code == 3
    assert "10% Transcribing" in out


@pytest.fixture
def ready_engines(monkeypatch):
    class ReadyHealth:
        def to_dict(self):
            return {"state": "ready", "summary": "ready"}

    monkeypatch.setattr("api.meetings.presets.resolve_preset", lambda _id: {
        "id": "test", "name": "Test", "engine": "test", "model_path": "test-model"})
    monkeypatch.setattr("api.meetings.probe_engine", lambda _preset: ReadyHealth())
    monkeypatch.setattr("api.meetings._require_usable_diarizer", lambda: {"state": "ready"})


def test_process_and_reprocess_enqueue_jobs(db_session, api, capsys, ready_engines):
    meeting = seed_meeting(db_session, status=MeetingStatus.COMPLETED)
    meeting.audio_filepath = "meeting.wav"
    meeting.raw_transcription = {"words": []}
    meeting.raw_diarization = {"turns": []}
    db_session.commit()

    code, out, _ = run(["reprocess", meeting.id, "reidentify"], api, capsys)
    assert code == 0
    assert db_session.query(Job).one().job_type == JobType.REIDENTIFY
    assert "reidentify" in out

    code, _, err = run(["reprocess", meeting.id, "reidentify"], api, capsys)
    assert code == 1
    assert err.startswith("error: ")

    other = seed_meeting(db_session, title="Nova", status=MeetingStatus.UPLOADED)
    other.audio_filepath = "other.wav"
    db_session.commit()
    code, out, _ = run(["process", other.id], api, capsys)
    assert code == 0
    assert db_session.query(Job).filter_by(meeting_id=other.id).one().job_type == JobType.PROCESS_MEETING


def test_words_below_keeps_only_low_confidence(db_session, api, capsys):
    meeting = seed_meeting(db_session)
    meeting.raw_transcription = {"words": [
        {"start": 221.0, "end": 221.4, "text": " Galo", "confidence": 0.31},
        {"start": 221.5, "end": 222.0, "text": " confirmou", "confidence": 0.92},
        {"start": 400.0, "end": 400.5, "text": " longe", "confidence": 0.1},
    ]}
    db_session.commit()

    code, out, _ = run(["words", meeting.id, "--from", "3:40", "--to", "3:50", "--below", "0.5"], api, capsys)

    assert code == 0
    assert out.strip().splitlines() == ["03:41 Galo 0.31"]


def test_export_writes_to_out_path(db_session, api, capsys, tmp_path):
    meeting = seed_meeting(db_session)
    maria = add_speaker(db_session, meeting, "SPEAKER_00", "Maria")
    add_segment(db_session, meeting, maria, 0, 0.0, 4.0, "Bom dia")
    db_session.commit()
    target = tmp_path / "out.txt"

    code, _, _ = run(["export", meeting.id, "--format", "txt", "--out", str(target)], api, capsys)

    assert code == 0
    assert "Bom dia" in target.read_text(encoding="utf-8")

    code, _, err = run(["export", meeting.id, "--format", "docx"], api, capsys)
    assert code == 1
    assert "--out" in err


def test_json_flag_prints_raw_api_json(db_session, api, capsys):
    seed_meeting(db_session, title="Obra 12")
    db_session.commit()

    code, out, _ = run(["--json", "list"], api, capsys)

    assert code == 0
    assert json.loads(out)[0]["title"] == "Obra 12"


def test_health_prints_status_and_failing_checks(capsys):
    # Canned answer: the real route probes the app's own database and storage.
    body = {"status": "degraded", "database": "ok", "whisper_cli": "missing: x", "disk_free_gb": 12.0}
    api = Api("http://t", transport=lambda *_: (200, json.dumps(body).encode()))

    code, out, _ = run(["health"], api, capsys)

    assert code == 0
    assert out.splitlines() == ["degraded", "whisper_cli: missing: x"]


def test_unreachable_server_exits_2(capsys):
    def refuse(method, url, headers, body):
        raise ConnectionRefusedError()

    api = Api(base_url="http://127.0.0.1:1", transport=refuse)

    code, out, err = run(["list"], api, capsys)

    assert code == 2
    assert "Transcriber is not running at http://127.0.0.1:1" in err
    assert out == ""


def test_connection_failure_maps_refusal_to_a_start_hint():
    error = connection_failure("http://127.0.0.1:8000", ConnectionRefusedError())

    assert isinstance(error, ApiError)
    assert error.status == 0
    assert "not running" in str(error)
    assert "start.ps1" in str(error)


def test_api_error_message_prefers_detail_text_and_health_message(api):
    def fixed(status, payload):
        return lambda method, url, headers, body: (status, json.dumps(payload).encode())

    with pytest.raises(ApiError) as plain:
        Api("http://t", transport=fixed(404, {"detail": "Meeting not found"})).get("/api/meetings/x")
    assert plain.value.status == 404
    assert str(plain.value) == "Meeting not found"

    with pytest.raises(ApiError) as blocked:
        Api("http://t", transport=fixed(409, {"detail": {"message": "engine blocked", "health": {}}})).post("/api/x")
    assert str(blocked.value) == "engine blocked"


def test_default_transport_streams_an_upload_and_reads_errors(tmp_path):
    """The real urllib path, against a throwaway local server (never the app)."""
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    received = {}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            received["body"] = self.rfile.read(int(self.headers["Content-Length"]))
            received["type"] = self.headers["Content-Type"]
            payload = b'{"ok": true}'
            self.send_response(200)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self):
            payload = b'{"detail": "Meeting not found"}'
            self.send_response(404)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        api = Api(base_url=f"http://127.0.0.1:{server.server_port}")
        audio = tmp_path / "r.wav"
        audio.write_bytes(b"A" * (2 * 1024 * 1024 + 5))

        assert api.upload("/api/meetings", {"title": "T"}, {"file": str(audio)}) == {"ok": True}
        with pytest.raises(ApiError) as missing:
            api.get("/api/meetings/x")
    finally:
        server.shutdown()
        server.server_close()

    assert received["type"].startswith("multipart/form-data; boundary=")
    assert b'name="title"\r\n\r\nT\r\n' in received["body"]
    assert b'name="file"; filename="r.wav"' in received["body"]
    assert received["body"].count(b"A") == 2 * 1024 * 1024 + 5
    assert (missing.value.status, str(missing.value)) == (404, "Meeting not found")


def test_clock_and_parse_clock_round_trip():
    assert clock(3723) == "1:02:03"
    assert clock(221) == "03:41"
    assert parse_clock("1:02:03") == 3723.0
    assert parse_clock("3:41") == 221.0
    assert parse_clock("90") == 90.0
    assert parse_clock("12.5") == 12.5
    assert parse_clock(clock(parse_clock("1:02:03"))) == 3723.0


def test_rename_sets_the_name_as_a_manual_identification(db_session, api, capsys):
    meeting = seed_meeting(db_session)
    anon = add_speaker(db_session, meeting, "SPEAKER_00")
    db_session.commit()

    code, out, _ = run(["rename", meeting.id, "SPEAKER_00", "Maria"], api, capsys)

    assert code == 0
    db_session.refresh(anon)
    assert (anon.display_name, anon.identified_by) == ("Maria", "manual")
    assert 'SPEAKER_00 "Maria" by=manual' in out


def test_rename_save_profile_asks_the_app_to_save_a_voice_profile(db_session, api, capsys):
    meeting = seed_meeting(db_session)
    anon = add_speaker(db_session, meeting, "SPEAKER_00")
    db_session.commit()
    sent = []

    def recording(method, url, headers, body):
        if method == "POST" and url.endswith("/api/speaker-profiles/save-from-speaker"):
            sent.append(json.loads(body))  # canned: the real route needs audio and ffmpeg
            return 200, json.dumps({"id": "p1", "name": "Maria"}).encode()
        return api.transport(method, url, headers, body)

    recorder = Api(base_url="http://test", transport=recording)

    code, out, _ = run(["rename", meeting.id, "SPEAKER_00", "Maria", "--save-profile"], recorder, capsys)

    assert code == 0
    assert sent == [{"speaker_id": anon.id, "meeting_id": meeting.id, "name": "Maria"}]
    assert "voice profile saved: Maria" in out

    sent.clear()
    run(["rename", meeting.id, "SPEAKER_00", "Maria"], recorder, capsys)
    assert sent == []


def test_edit_does_not_teach_vocabulary_unless_asked_to_learn(db_session, api, capsys):
    meeting = seed_meeting(db_session)
    entry = VocabularyEntry(term="Garrah")
    db_session.add(entry)
    ana = add_speaker(db_session, meeting, "SPEAKER_00", "Ana")
    add_segment(db_session, meeting, ana, 0, 0.0, 1.0, "Galo", original_text="Galo")
    db_session.commit()

    code, out, _ = run(["edit", meeting.id, "#0", "Garrah"], api, capsys)

    assert code == 0
    assert "#0 00:00 Ana: Garrah [edited]" in out
    db_session.refresh(entry)
    assert not entry.misheard_as

    code, _, _ = run(["edit", meeting.id, "#0", "Galo"], api, capsys)
    assert code == 0
    code, _, _ = run(["edit", meeting.id, "#0", "Garrah", "--learn"], api, capsys)
    assert code == 0
    db_session.refresh(entry)
    assert entry.misheard_as == [{"form": "Galo", "count": 1}]


def test_revert_restores_the_text_and_refuses_an_unedited_segment(db_session, api, capsys):
    meeting = seed_meeting(db_session)
    ana = add_speaker(db_session, meeting, "SPEAKER_00", "Ana")
    add_segment(db_session, meeting, ana, 0, 0.0, 1.0, "original", original_text="original")
    db_session.commit()
    run(["edit", meeting.id, "#0", "mudado"], api, capsys)

    code, out, _ = run(["revert", meeting.id, "#0"], api, capsys)

    assert code == 0
    assert "#0 00:00 Ana: original" in out
    assert "[edited]" not in out

    code, out, err = run(["revert", meeting.id, "#0"], api, capsys)
    assert code == 1
    assert "Segment has no edit to revert" in err
    assert out == ""


def test_assign_moves_a_segment_to_a_new_or_existing_speaker(db_session, api, capsys):
    meeting = seed_meeting(db_session)
    ana = add_speaker(db_session, meeting, "SPEAKER_00", "Ana")
    segment = add_segment(db_session, meeting, ana, 0, 0.0, 1.0, "oi")
    db_session.commit()

    code, out, _ = run(["assign", meeting.id, "#0", "new:Carla"], api, capsys)

    assert code == 0
    carla = db_session.query(Speaker).filter_by(label="MANUAL_1").one()
    assert carla.display_name == "Carla"
    db_session.refresh(segment)
    assert segment.speaker_id == carla.id
    assert "#0 00:00 Carla: oi [moved]" in out

    code, _, _ = run(["assign", meeting.id, "#0", "SPEAKER_00"], api, capsys)
    assert code == 0
    db_session.refresh(segment)
    assert segment.speaker_id == ana.id


def seed_spoken_segments(db, meeting, speaker, heard):
    """One Segment holding the Words `heard` (a Word every 0.5 s), then one more after it."""
    meeting.raw_transcription = {"words": [
        {"start": i * 0.5, "end": i * 0.5 + 0.4, "text": f" {text}", "confidence": 0.9}
        for i, text in enumerate([*heard, "fim"])
    ]}
    last = (len(heard) - 1) * 0.5 + 0.4
    segment = add_segment(db, meeting, speaker, 0, 0.0, last, " ".join(heard))
    after = add_segment(db, meeting, speaker, 1, len(heard) * 0.5, len(heard) * 0.5 + 0.4, "fim")
    db.commit()
    return segment, after


def test_split_before_words_cuts_where_the_second_half_starts(
    db_session, api, capsys, isolated_preferences,
):
    meeting = seed_meeting(db_session)
    ana = add_speaker(db_session, meeting, "SPEAKER_00", "Ana")
    segment, after = seed_spoken_segments(
        db_session, meeting, ana, ["tudo", "bem?", "Quem", "manda", "aqui"],
    )

    code, out, _ = run(["split", meeting.id, "#0", "--before", "quem, MANDA"], api, capsys)

    assert code == 0
    assert out.splitlines() == [
        "#0 00:00 Ana: tudo bem?",
        "#1 00:01 Ana: Quem manda aqui",
        "Segments after #0 are renumbered (+1).",
    ]
    db_session.refresh(after)
    assert after.order == 2


def test_split_before_words_not_among_the_segments_words_exits_1(
    db_session, api, capsys, isolated_preferences,
):
    meeting = seed_meeting(db_session)
    ana = add_speaker(db_session, meeting, "SPEAKER_00", "Ana")
    seed_spoken_segments(db_session, meeting, ana, ["tudo", "bem", "quem", "manda"])

    code, out, err = run(["split", meeting.id, "#0", "--before", "quem sabe"], api, capsys)

    assert code == 1
    assert "'quem sabe' is not among #0's Words as heard" in err
    assert out == ""
    db_session.refresh(meeting)
    assert meeting.split_times is None


def test_split_before_the_first_word_is_no_cut(db_session, api, capsys, isolated_preferences):
    meeting = seed_meeting(db_session)
    ana = add_speaker(db_session, meeting, "SPEAKER_00", "Ana")
    seed_spoken_segments(db_session, meeting, ana, ["tudo", "bem", "quem"])

    code, _, err = run(["split", meeting.id, "#0", "--before", "tudo"], api, capsys)

    assert code == 1
    assert "is not among #0's Words as heard" in err


def test_split_before_words_that_occur_twice_asks_for_at(
    db_session, api, capsys, isolated_preferences,
):
    meeting = seed_meeting(db_session)
    ana = add_speaker(db_session, meeting, "SPEAKER_00", "Ana")
    seed_spoken_segments(db_session, meeting, ana, ["sim", "ok", "sim", "ok"])

    code, out, err = run(["split", meeting.id, "#0", "--before", "ok"], api, capsys)

    assert code == 1
    assert "'ok' occurs 2 times in #0" in err
    assert "00:00 (--at 0.5)" in err and "00:01 (--at 1.5)" in err
    assert "--at" in err
    assert out == ""
    db_session.refresh(meeting)
    assert meeting.split_times is None


def test_split_at_a_time_and_to_a_new_speaker(db_session, api, capsys, isolated_preferences):
    meeting = seed_meeting(db_session)
    ana = add_speaker(db_session, meeting, "SPEAKER_00", "Ana")
    segment, _ = seed_spoken_segments(db_session, meeting, ana, ["tudo", "bem", "quem", "manda"])

    code, out, _ = run(
        ["split", meeting.id, "#0", "--at", "1.0", "--speaker", "new:Carla"], api, capsys,
    )

    assert code == 0
    assert out.splitlines()[:2] == [
        "#0 00:00 Ana: tudo bem",
        "#1 00:01 Carla: quem manda [moved]",
    ]
    carla = db_session.query(Speaker).filter_by(label="MANUAL_1").one()
    assert carla.segment_count == 1
    db_session.refresh(meeting)
    assert meeting.split_times == [1.0]


def test_split_needs_exactly_one_of_at_and_before(db_session, api, capsys):
    meeting = seed_meeting(db_session)
    db_session.commit()

    for argv in (["split", meeting.id, "#0"], ["split", meeting.id, "#0", "--at", "1", "--before", "x"]):
        with pytest.raises(SystemExit):
            main(argv, api=api)
        assert "--at" in capsys.readouterr().err


def test_unsplit_joins_the_segment_with_the_next(db_session, api, capsys, isolated_preferences):
    meeting = seed_meeting(db_session)
    ana = add_speaker(db_session, meeting, "SPEAKER_00", "Ana")
    seed_spoken_segments(db_session, meeting, ana, ["tudo", "bem", "quem", "manda"])
    assert run(["split", meeting.id, "#0", "--at", "1.0"], api, capsys)[0] == 0

    code, out, _ = run(["unsplit", meeting.id, "#0"], api, capsys)

    assert code == 0
    assert out.splitlines() == [
        "#0 00:00 Ana: tudo bem quem manda",
        "Segments after #0 are renumbered (-1).",
    ]
    db_session.refresh(meeting)
    assert meeting.split_times == []


def test_add_speaker_and_merge(db_session, api, capsys):
    meeting = seed_meeting(db_session)
    ana = add_speaker(db_session, meeting, "SPEAKER_00", "Ana")
    add_segment(db_session, meeting, ana, 0, 0.0, 1.0, "oi")
    db_session.commit()

    code, out, _ = run(["add-speaker", meeting.id, "Carla"], api, capsys)
    assert code == 0
    assert 'MANUAL_1 "Carla" by=manual' in out

    code, out, _ = run(["merge", meeting.id, "SPEAKER_00", "MANUAL_1"], api, capsys)
    assert code == 0
    assert 'MANUAL_1 "Carla"' in out
    assert db_session.query(Speaker).filter_by(label="SPEAKER_00").count() == 0


def test_set_updates_only_the_given_fields(db_session, api, capsys):
    meeting = seed_meeting(db_session, title="Obra 12")
    meeting.vocabulary = "Garrah"
    db_session.commit()

    code, _, _ = run(["set", meeting.id, "--participants", "Ana, Bruno"], api, capsys)

    assert code == 0
    db_session.refresh(meeting)
    assert (meeting.title, meeting.vocabulary, meeting.participants) == ("Obra 12", "Garrah", "Ana, Bruno")

    code, _, err = run(["set", meeting.id], api, capsys)
    assert code == 1
    assert "nothing to set" in err


def test_suspects_prints_repeated_and_low_confidence_sections(db_session, api, capsys):
    meeting = seed_meeting(db_session)
    maria = add_speaker(db_session, meeting, "SPEAKER_00", "Maria")
    for order in range(3):
        add_segment(db_session, meeting, maria, order, 100.0 + order * 5, 104.0 + order * 5, "Obrigado.")
    add_segment(db_session, meeting, maria, 3, 221.0, 230.0, "Galo confirmou algo de Do", confidence=0.9)
    add_segment(db_session, meeting, maria, 4, 231.0, 236.0, "Palavra duvidosa", confidence=0.9)
    meeting.raw_transcription = {"words": [
        {"start": 221.0, "end": 221.4, "text": " Galo", "confidence": 0.3},
        {"start": 221.5, "end": 222.0, "text": " confirmou", "confidence": 0.95},
        {"start": 223.0, "end": 223.4, "text": " algo", "confidence": 0.14},
        {"start": 224.0, "end": 224.4, "text": " de", "confidence": 0.8},
        {"start": 225.0, "end": 225.4, "text": " Do", "confidence": 0.37},
        {"start": 232.0, "end": 232.4, "text": " duvidosa", "confidence": 0.39},
    ]}
    db_session.commit()

    code, out, _ = run(["suspects", meeting.id], api, capsys)

    assert code == 0
    assert "REPEATED (possible hallucination over silence)" in out
    assert '  01:40-01:54 #0-#2 x3 "obrigado"' in out
    assert "LOW-CONFIDENCE PASSAGES (worst first)" in out
    passages = [line for line in out.splitlines() if "| weak:" in line]
    assert len(passages) == 2
    assert passages[0].startswith("  #3 ") and passages[0].endswith("| weak: Galo 0.30, algo 0.14, Do 0.37")
    assert passages[1].startswith("  #4 ") and passages[1].endswith("| weak: duvidosa 0.39")
    assert "CORRECTED BY VOCABULARY" not in out
    assert "LOW-CONFIDENCE WORDS" not in out and "LOW-CONFIDENCE SEGMENTS" not in out


def test_suspects_limit_caps_each_section_and_says_so(db_session, api, capsys):
    meeting = seed_meeting(db_session)
    maria = add_speaker(db_session, meeting, "SPEAKER_00", "Maria")
    words = []
    for order in range(3):
        start = order * 10.0
        add_segment(db_session, meeting, maria, order, start, start + 5, f"fala {order}", confidence=0.9)
        words.append({"start": start + 1, "end": start + 1.4, "text": " fala", "confidence": 0.1 + order * 0.1})
    meeting.raw_transcription = {"words": words}
    db_session.commit()

    code, out, _ = run(["suspects", meeting.id, "--limit", "2"], api, capsys)

    assert code == 0
    assert "LOW-CONFIDENCE PASSAGES (worst first) (showing 2 of 3)" in out
    assert "fala 0" in out and "fala 1" in out
    assert "fala 2" not in out


def test_suspects_lists_vocabulary_corrections(db_session, api, capsys):
    meeting = seed_meeting(db_session)
    maria = add_speaker(db_session, meeting, "SPEAKER_00", "Maria")
    add_segment(
        db_session, meeting, maria, 77, 72.0, 75.0, "Garrah chegou", confidence=0.9,
        corrections=[{"start": 72.0, "end": 72.4, "heard": " Galo", "term": "Garrah", "rule": "similar"}],
    )
    db_session.commit()

    code, out, _ = run(["suspects", meeting.id], api, capsys)

    assert code == 0
    assert "CORRECTED BY VOCABULARY" in out
    assert "  #77 01:12 Galo->Garrah (rule similar)" in out


def review_meeting(db):
    meeting = seed_meeting(db)
    ana = add_speaker(db, meeting, "SPEAKER_00", "Ana")
    bia = add_speaker(db, meeting, "SPEAKER_01", "Participant 2")
    add_segment(db, meeting, ana, 0, 0.0, 5.0, "Galo disse isso", original_text="Galo disse isso")
    add_segment(db, meeting, bia, 1, 70.0, 75.0, "Concordo", original_text="Concordo")
    db.commit()
    return meeting, ana, bia


def stored_notes(db):
    from models import ReviewNote

    db.expire_all()
    return db.query(ReviewNote).order_by(ReviewNote.created_at).all()


def test_ask_leaves_a_question_anchored_at_the_segment(db_session, api, capsys):
    meeting, *_ = review_meeting(db_session)

    code, out, _ = run(["ask", meeting.id, "#1", "Quem fala aqui?"], api, capsys)

    assert code == 0
    (note,) = stored_notes(db_session)
    assert (note.kind, note.author, note.status) == ("question", "agent", "open")
    assert (note.start_time, note.end_time) == (70.0, 75.0)
    assert note.body == "Quem fala aqui?"
    assert f"n:{note.id[:8]} #1 01:10 question/open agent: Quem fala aqui?" in out


def test_note_leaves_a_comment_by_the_agent(db_session, api, capsys):
    meeting, *_ = review_meeting(db_session)

    code, _, _ = run(["note", meeting.id, "#0", "Ruido de fundo"], api, capsys)

    assert code == 0
    (note,) = stored_notes(db_session)
    assert (note.kind, note.author) == ("comment", "agent")
    assert (note.start_time, note.end_time) == (0.0, 5.0)


def test_suggest_leaves_a_text_fix_expecting_the_current_text(db_session, api, capsys):
    meeting, *_ = review_meeting(db_session)

    code, out, _ = run(
        ["suggest", meeting.id, "#0", "Garrah disse isso", "--why", "parece o nome da obra"], api, capsys)

    assert code == 0
    (note,) = stored_notes(db_session)
    assert note.kind == "text"
    assert note.body == "parece o nome da obra"
    assert note.payload == {"expected_text": "Galo disse isso", "proposed_text": "Garrah disse isso"}
    assert "-> Garrah disse isso" in out


def test_suggest_requires_a_reason(db_session, api, capsys):
    meeting, *_ = review_meeting(db_session)

    with pytest.raises(SystemExit):
        run(["suggest", meeting.id, "#0", "Garrah disse isso"], api, capsys)

    assert stored_notes(db_session) == []


def test_suggest_name_uses_the_evidence_segment_as_the_range(db_session, api, capsys):
    meeting, *_ = review_meeting(db_session)

    code, out, _ = run(
        ["suggest-name", meeting.id, "SPEAKER_01", "Bia", "--at", "#1", "--why", "se apresenta"], api, capsys)

    assert code == 0
    (note,) = stored_notes(db_session)
    assert note.kind == "speaker_name"
    assert note.payload == {"label": "SPEAKER_01", "name": "Bia"}
    assert (note.start_time, note.end_time) == (70.0, 75.0)
    assert "-> Bia" in out


def test_suggest_move_targets_an_existing_or_a_new_speaker(db_session, api, capsys):
    meeting, *_ = review_meeting(db_session)

    code, _, _ = run(["suggest-move", meeting.id, "#0", "SPEAKER_01", "--why", "e a Bia"], api, capsys)
    assert code == 0
    code, _, _ = run(["suggest-move", meeting.id, "#0", "new:Carla", "--why", "terceira voz"], api, capsys)
    assert code == 0

    first, second = stored_notes(db_session)
    assert (first.kind, first.payload) == ("speaker_move", {"target_label": "SPEAKER_01"})
    assert second.payload == {"new_name": "Carla"}
    assert (first.start_time, first.end_time) == (0.0, 5.0)


def test_suggest_move_refuses_an_empty_new_name(db_session, api, capsys):
    meeting, *_ = review_meeting(db_session)

    code, _, err = run(["suggest-move", meeting.id, "#0", "new:", "--why", "x"], api, capsys)

    assert code == 1
    assert "new:" in err
    assert stored_notes(db_session) == []


def test_suggest_merge_names_both_speakers(db_session, api, capsys):
    meeting, *_ = review_meeting(db_session)

    code, _, _ = run(
        ["suggest-merge", meeting.id, "SPEAKER_00", "SPEAKER_01", "--at", "#0", "--why", "mesma voz"],
        api, capsys)

    assert code == 0
    (note,) = stored_notes(db_session)
    assert note.kind == "speaker_merge"
    assert note.payload == {"source_label": "SPEAKER_00", "target_label": "SPEAKER_01"}
    assert (note.start_time, note.end_time) == (0.0, 5.0)


def test_notes_lists_one_line_per_note_and_filters_by_status(db_session, api, capsys):
    from models import ReviewNote

    meeting, *_ = review_meeting(db_session)

    def make(**kw):
        fields = dict(meeting_id=meeting.id, start_time=0.0, end_time=5.0, author="agent",
                      kind="comment", body="x", status="open")
        fields.update(kw)
        note = ReviewNote(**fields)
        db_session.add(note)
        db_session.flush()
        return note

    text = make(start_time=0.0, kind="text", body="parece o nome",
                payload={"expected_text": "Galo disse isso", "proposed_text": "Garrah disse isso"})
    asked = make(start_time=70.0, end_time=75.0, kind="question", body="Quem?", status="answered",
                 answer="A Bia")
    closed = make(start_time=30.0, end_time=33.0, body="velho", status="done", reply="feito")
    named = make(start_time=71.0, end_time=74.0, kind="speaker_name", body="se apresenta",
                 payload={"label": "SPEAKER_01", "name": "Bia"})
    db_session.commit()

    code, out, _ = run(["notes", meeting.id], api, capsys)

    lines = out.splitlines()
    assert code == 0
    assert lines == [
        f"n:{text.id[:8]} #0 00:00 text/open agent: parece o nome -> Garrah disse isso",
        f"n:{closed.id[:8]} #? 00:30 comment/done agent: velho reply: feito",
        f"n:{asked.id[:8]} #1 01:10 question/answered agent: Quem? answer: A Bia",
        f"n:{named.id[:8]} #1 01:11 speaker_name/open agent: se apresenta -> Bia",
    ]
    _, out, _ = run(["notes", meeting.id, "--status", "open"], api, capsys)
    assert [line.split()[0] for line in out.splitlines()] == [f"n:{text.id[:8]}", f"n:{named.id[:8]}"]
    _, out, _ = run(["notes", meeting.id, "--status", "answered"], api, capsys)
    assert [line.split()[0] for line in out.splitlines()] == [f"n:{asked.id[:8]}"]
    _, out, _ = run(["notes", meeting.id, "--status", "resolved"], api, capsys)
    assert [line.split()[0] for line in out.splitlines()] == [f"n:{closed.id[:8]}"]


def test_close_marks_a_note_done_with_a_reply(db_session, api, capsys):
    from models import ReviewNote

    meeting, *_ = review_meeting(db_session)
    note = ReviewNote(meeting_id=meeting.id, start_time=0.0, end_time=5.0, author="user",
                      kind="comment", body="troque o nome", status="open")
    db_session.add(note)
    db_session.commit()
    note_id = note.id

    code, out, _ = run(["close", meeting.id, f"n:{note_id[:8]}", "--reply", "troquei"], api, capsys)

    assert code == 0
    (stored,) = stored_notes(db_session)
    assert (stored.status, stored.reply) == ("done", "troquei")
    assert f"n:{note_id[:8]} #0 00:00 comment/done user: troque o nome reply: troquei" in out


def test_close_rejects_a_short_or_unknown_note_handle(db_session, api, capsys):
    from models import ReviewNote

    meeting, *_ = review_meeting(db_session)
    db_session.add(ReviewNote(meeting_id=meeting.id, start_time=0.0, end_time=5.0, author="agent",
                              kind="comment", body="x", status="open"))
    db_session.commit()

    code, _, err = run(["close", meeting.id, "zzzz"], api, capsys)
    assert code == 1
    assert "No Note matches" in err
    code, _, err = run(["close", meeting.id, "ab"], api, capsys)
    assert code == 1


def test_a_note_cannot_be_left_on_a_missing_segment(db_session, api, capsys):
    meeting, *_ = review_meeting(db_session)

    code, _, err = run(["ask", meeting.id, "#9", "Quem?"], api, capsys)

    assert code == 1
    assert "No Segment #9" in err
    assert stored_notes(db_session) == []


def test_piped_stdout_is_line_buffered():
    import io

    from transcriber_cli.__main__ import _configure_streams

    pipe = io.TextIOWrapper(io.BytesIO(), encoding="cp1252")

    _configure_streams([pipe])

    assert pipe.line_buffering is True
    assert pipe.encoding == "utf-8"
