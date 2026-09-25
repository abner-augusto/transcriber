import pytest

from engines import Turn, Word, DiarizationResult
from models import JobType, Meeting, VocabularyEntry
from tasks.process_meeting import process_meeting_task
from tasks.reprocess_task import reapply_vocabulary_task

from . import task_harness as h
from .fakes import FakeTranscriber
from preferences import VocabularyCorrectionPrefs


def test_process_applies_and_persists_vocabulary_without_changing_raw_words(
    monkeypatch, tmp_path
):
    words = [Word(0.1, 0.6, " Garra", 0.8)]
    harness = h.install(
        monkeypatch, tmp_path,
        transcriber=FakeTranscriber(words),
        diarization=DiarizationResult(turns=[Turn(0, 1, "SPEAKER_00")]),
    )
    monkeypatch.setattr("run_config.resolve_run_config", lambda meeting: h.TEST_RUN_CONFIG.model_copy(
        update={"vocabulary_correction": VocabularyCorrectionPrefs(enabled=True)}
    ))
    meeting_id = harness.meeting(vocabulary="Vocabulary: Garrah")
    job_id = harness.job(meeting_id, JobType.PROCESS_MEETING)

    assert process_meeting_task(meeting_id, job_id)["status"] == "completed"
    meeting = harness.load(meeting_id)
    assert meeting.segments[0].text == "Garrah"
    assert meeting.segments[0].corrections == [{
        "start": 0.1, "end": 0.6, "heard": "Garra", "term": "Garrah", "rule": "similar"
    }]
    assert meeting.raw_transcription["words"][0]["text"] == " Garra"


def test_disabled_preference_keeps_transcription_and_segments_uncorrected(monkeypatch, tmp_path):
    words = [Word(0.1, 0.6, " Galo", 0.8)]
    harness = h.install(
        monkeypatch, tmp_path,
        transcriber=FakeTranscriber(words),
        diarization=DiarizationResult(turns=[Turn(0, 1, "SPEAKER_00")]),
    )
    monkeypatch.setattr("run_config.resolve_run_config", lambda meeting: h.TEST_RUN_CONFIG.model_copy(
        update={"vocabulary_correction": VocabularyCorrectionPrefs(enabled=False)}
    ))
    meeting_id = harness.meeting(vocabulary="Vocabulary: Garrah")
    job_id = harness.job(meeting_id, JobType.PROCESS_MEETING)

    assert process_meeting_task(meeting_id, job_id)["status"] == "completed"
    meeting = harness.load(meeting_id)
    assert meeting.segments[0].text == "Galo"
    assert meeting.segments[0].corrections == []


def test_reapply_vocabulary_updates_segments_and_keeps_existing_speakers(
    monkeypatch, tmp_path
):
    words = [Word(0.1, 0.6, " Galo", 0.8)]
    harness = h.install(
        monkeypatch, tmp_path,
        transcriber=FakeTranscriber(words),
        diarization=DiarizationResult(turns=[Turn(0, 1, "SPEAKER_00")]),
    )
    monkeypatch.setattr("run_config.resolve_run_config", lambda meeting: h.TEST_RUN_CONFIG.model_copy(
        update={"vocabulary_correction": VocabularyCorrectionPrefs(enabled=False)}
    ))
    meeting_id = harness.meeting()
    process_job = harness.job(meeting_id, JobType.PROCESS_MEETING)
    assert process_meeting_task(meeting_id, process_job)["status"] == "completed"

    with harness.session_factory() as db:
        meeting = db.get(Meeting, meeting_id)
        meeting.vocabulary = "Vocabulary: Garrah"
        speaker = meeting.speakers[0]
        speaker.display_name = "Manual name"
        speaker.identified_by = "manual"
        speaker_id = speaker.id
        db.add(VocabularyEntry(term="Garrah", misheard_as=[{"form": "Galo", "count": 2}]))
        db.commit()

    monkeypatch.setattr("run_config.resolve_run_config", lambda meeting: h.TEST_RUN_CONFIG.model_copy(
        update={"vocabulary_correction": VocabularyCorrectionPrefs(enabled=True)}
    ))
    job_id = harness.job(meeting_id, JobType.REAPPLY_VOCABULARY)
    assert reapply_vocabulary_task(meeting_id, job_id)["status"] == "completed"
    meeting = harness.load(meeting_id)
    assert [
        (s.id, s.display_name, s.identified_by, s.segment_count, s.total_speaking_time)
        for s in meeting.speakers
    ] == [(speaker_id, "Manual name", "manual", 1, 0.5)]
    assert meeting.segments[0].text == "Garrah"
    assert meeting.segments[0].corrections[0]["rule"] == "misheard"


def _processed_segment(monkeypatch, tmp_path, words: list[Word], vocabulary: str):
    harness = h.install(
        monkeypatch, tmp_path,
        transcriber=FakeTranscriber(words),
        diarization=DiarizationResult(turns=[Turn(0, 10, "SPEAKER_00")]),
    )
    monkeypatch.setattr("run_config.resolve_run_config", lambda meeting: h.TEST_RUN_CONFIG.model_copy(
        update={"vocabulary_correction": VocabularyCorrectionPrefs(enabled=True)}
    ))
    meeting_id = harness.meeting(vocabulary=vocabulary)
    job_id = harness.job(meeting_id, JobType.PROCESS_MEETING)
    assert process_meeting_task(meeting_id, job_id)["status"] == "completed"
    (segment,) = harness.load(meeting_id).segments
    return segment


@pytest.mark.parametrize(
    ("heard", "vocabulary", "expected_text", "expected_terms"),
    [
        pytest.param(
            [" Garrah,", " confirmou."], "Vocabulary: Garrah",
            "Garrah, confirmou.", [],
            id="term-already-spelled-right-before-punctuation",
        ),
        pytest.param(
            [" (Garra)", " confirmou."], "Vocabulary: Garrah",
            "(Garrah) confirmou.", ["Garrah"],
            id="punctuation-around-a-corrected-word-survives",
        ),
        pytest.param(
            [" Stefanopoulos", " chegou."], "Vocabulary: Stephanopoulos",
            "Stephanopoulos chegou.", ["Stephanopoulos"],
            id="ph-sounds-like-f",
        ),
        pytest.param(
            [" Ga", " rr", " ah"], "Vocabulary: Garrah, Banco Central do Brasil",
            "Ga rr ah", [],
            id="one-word-term-matches-at-most-two-words",
        ),
    ],
)
def test_vocabulary_correction_rules_seen_in_processed_segments(
    monkeypatch, tmp_path, heard, vocabulary, expected_text, expected_terms
):
    words = [Word(0.1 + i * 0.3, 0.35 + i * 0.3, text) for i, text in enumerate(heard)]

    segment = _processed_segment(monkeypatch, tmp_path, words, vocabulary)

    assert segment.text == expected_text
    assert [correction["term"] for correction in segment.corrections] == expected_terms


@pytest.mark.parametrize("job_type", [JobType.REAPPLY_VOCABULARY, JobType.REIDENTIFY])
def test_reprocessing_keeps_an_edited_segment_and_gives_it_no_corrections(
    monkeypatch, tmp_path, job_type
):
    from tasks.reprocess_task import reidentify_task

    harness = h.install(
        monkeypatch, tmp_path,
        transcriber=FakeTranscriber([Word(0.1, 0.6, " Garra", 0.8)]),
        diarization=DiarizationResult(turns=[Turn(0, 1, "SPEAKER_00")]),
    )
    monkeypatch.setattr("run_config.resolve_run_config", lambda meeting: h.TEST_RUN_CONFIG.model_copy(
        update={"vocabulary_correction": VocabularyCorrectionPrefs(enabled=True)}
    ))
    meeting_id = harness.meeting(vocabulary="Vocabulary: Garrah")
    assert process_meeting_task(meeting_id, harness.job(meeting_id, JobType.PROCESS_MEETING))["status"] == "completed"
    with harness.session_factory() as db:
        (segment,) = db.get(Meeting, meeting_id).segments
        assert segment.corrections
        segment.text = "Garrah, typed by hand"
        segment.is_edited = True
        db.commit()

    task = {JobType.REAPPLY_VOCABULARY: reapply_vocabulary_task, JobType.REIDENTIFY: reidentify_task}[job_type]
    assert task(meeting_id, harness.job(meeting_id, job_type))["status"] == "completed"

    (segment,) = harness.load(meeting_id).segments
    assert (segment.text, segment.is_edited, segment.corrections) == ("Garrah, typed by hand", True, [])


def test_each_correction_is_stored_on_the_segment_whose_time_contains_it(monkeypatch, tmp_path):
    harness = h.install(
        monkeypatch, tmp_path,
        transcriber=FakeTranscriber([
            Word(0.1, 0.6, " Garra", 0.8), Word(0.7, 0.9, " chegou.", 0.8),
            Word(2.1, 2.6, " Stefanopoulos", 0.8), Word(2.7, 2.9, " respondeu.", 0.8),
        ]),
        diarization=DiarizationResult(turns=[Turn(0, 1.5, "SPEAKER_00"), Turn(1.5, 3.5, "SPEAKER_01")]),
    )
    monkeypatch.setattr("run_config.resolve_run_config", lambda meeting: h.TEST_RUN_CONFIG.model_copy(
        update={"vocabulary_correction": VocabularyCorrectionPrefs(enabled=True)}
    ))
    meeting_id = harness.meeting(vocabulary="Vocabulary: Garrah, Stephanopoulos")
    assert process_meeting_task(meeting_id, harness.job(meeting_id, JobType.PROCESS_MEETING))["status"] == "completed"

    segments = harness.load(meeting_id).segments
    assert [(s.text, [(c["start"], c["term"]) for c in s.corrections]) for s in segments] == [
        ("Garrah chegou.", [(0.1, "Garrah")]),
        ("Stephanopoulos respondeu.", [(2.1, "Stephanopoulos")]),
    ]
