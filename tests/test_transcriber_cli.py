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
    add_segment(db_session, meeting, maria, 3, 221.0, 225.0, "Galo confirmou", confidence=0.9)
    meeting.raw_transcription = {"words": [
        {"start": 221.0, "end": 221.4, "text": " Galo", "confidence": 0.3},
        {"start": 221.5, "end": 222.0, "text": " confirmou", "confidence": 0.95},
    ]}
    db_session.commit()

    code, out, _ = run(["suspects", meeting.id], api, capsys)

    assert code == 0
    assert "REPEATED (possible hallucination over silence)" in out
    assert '  01:40-01:54 #0-#2 x3 "obrigado"' in out
    assert "LOW-CONFIDENCE WORDS" in out
    assert "  #3 03:41 Galo (0.30) | #3 03:41 Maria: Galo confirmou" in out
    assert "CORRECTED BY VOCABULARY" not in out
    assert "LOW-CONFIDENCE SEGMENTS" not in out


def test_suspects_limit_caps_each_section_and_says_so(db_session, api, capsys):
    meeting = seed_meeting(db_session)
    maria = add_speaker(db_session, meeting, "SPEAKER_00", "Maria")
    for order in range(3):
        add_segment(db_session, meeting, maria, order, order * 10.0, order * 10.0 + 5, f"fala {order}", confidence=0.2)
    db_session.commit()

    code, out, _ = run(["suspects", meeting.id, "--limit", "2"], api, capsys)

    assert code == 0
    assert "LOW-CONFIDENCE SEGMENTS (showing 2 of 3)" in out
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



def test_piped_stdout_is_line_buffered():
    import io

    from transcriber_cli.__main__ import _configure_streams

    pipe = io.TextIOWrapper(io.BytesIO(), encoding="cp1252")

    _configure_streams([pipe])

    assert pipe.line_buffering is True
    assert pipe.encoding == "utf-8"
