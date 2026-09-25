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


def _processed_segment(
    monkeypatch, tmp_path, words: list[Word], vocabulary: str, misheard: tuple = ()
):
    harness = h.install(
        monkeypatch, tmp_path,
        transcriber=FakeTranscriber(words),
        diarization=DiarizationResult(turns=[Turn(0, 10, "SPEAKER_00")]),
    )
    monkeypatch.setattr("run_config.resolve_run_config", lambda meeting: h.TEST_RUN_CONFIG.model_copy(
        update={"vocabulary_correction": VocabularyCorrectionPrefs(enabled=True)}
    ))
    with harness.session_factory() as db:
        for term, form, count in misheard:
            db.add(VocabularyEntry(term=term, misheard_as=[{"form": form, "count": count}]))
        db.commit()
    meeting_id = harness.meeting(vocabulary=vocabulary)
    job_id = harness.job(meeting_id, JobType.PROCESS_MEETING)
    assert process_meeting_task(meeting_id, job_id)["status"] == "completed"
    (segment,) = harness.load(meeting_id).segments
    return segment


def _spoken(*texts: str) -> list[Word]:
    """Words 0.3 s apart: close enough to merge into one heard phrase."""
    return [Word(0.1 + i * 0.3, 0.35 + i * 0.3, text) for i, text in enumerate(texts)]


@pytest.mark.parametrize(
    ("words", "vocabulary", "misheard", "expected_text", "expected_terms"),
    [
        pytest.param(
            _spoken(" Garra", " e", " Doker"), "Speakers: Ana, Bob\nVocabulary: Garrah, Docker; GARrah",
            (), "Garrah e Docker", ["Garrah", "Docker"],
            id="labelled-vocabulary-lines-are-parsed",
        ),
        pytest.param(
            _spoken(" Sao", " Paulo"), "São Paulo, C++; são paulo",
            (), "São Paulo", ["São Paulo"],
            id="free-form-vocabulary-is-parsed",
        ),
        pytest.param(
            _spoken(" Galo"), "Vocabulary: Garrah",
            (("Garrah", "Galo", 1),), "Garrah", ["Garrah"],
            id="misheard-form-heard-once-applies-when-the-term-is-in-the-meeting",
        ),
        pytest.param(
            _spoken(" Galo"), "",
            (("Garrah", "Galo", 1),), "Galo", [],
            id="misheard-form-heard-once-is-ignored-elsewhere",
        ),
        pytest.param(
            _spoken(" Galo"), "",
            (("Garrah", "Galo", 2),), "Garrah", ["Garrah"],
            id="misheard-form-heard-twice-applies-everywhere",
        ),
        pytest.param(
            [Word(0.1, 0.5, " Gar", 0.9), Word(0.31, 0.4, " rah,", 0.7)], "Vocabulary: Garrah",
            (), "Garrah,", ["Garrah"],
            id="adjacent-words-merge-and-keep-trailing-punctuation",
        ),
        pytest.param(
            [Word(0.1, 0.3, " Gar"), Word(0.81, 1.0, " rah")], "Vocabulary: Garrah",
            (), "Gar rah", [],
            id="a-pause-between-words-blocks-the-merge",
        ),
        pytest.param(
            _spoken(" Asafrao"), "Açafrão",
            (), "Açafrão", ["Açafrão"],
            id="cedilla-sounds-like-s",
        ),
        pytest.param(
            _spoken(" Joao", " e", " ana"), "João, Ana",
            (), "João e ana", ["João"],
            id="accents-are-restored-but-three-letter-terms-are-left-alone",
        ),
        pytest.param(
            _spoken(" para", "quedas"), "Parakeet",
            (), "paraquedas", [],
            id="an-unrelated-common-word-is-unchanged",
        ),
        pytest.param(
            _spoken(" Garrah,", " confirmou."), "Vocabulary: Garrah",
            (), "Garrah, confirmou.", [],
            id="term-already-spelled-right-before-punctuation",
        ),
        pytest.param(
            _spoken(" (Garra)", " confirmou."), "Vocabulary: Garrah",
            (), "(Garrah) confirmou.", ["Garrah"],
            id="punctuation-around-a-corrected-word-survives",
        ),
        pytest.param(
            _spoken(" Stefanopoulos", " chegou."), "Vocabulary: Stephanopoulos",
            (), "Stephanopoulos chegou.", ["Stephanopoulos"],
            id="ph-sounds-like-f",
        ),
        pytest.param(
            _spoken(" Ga", " rr", " ah"), "Vocabulary: Garrah, Banco Central do Brasil",
            (), "Ga rr ah", [],
            id="one-word-term-matches-at-most-two-words",
        ),
    ],
)
def test_vocabulary_correction_rules_seen_in_processed_segments(
    monkeypatch, tmp_path, words, vocabulary, misheard, expected_text, expected_terms
):
    segment = _processed_segment(monkeypatch, tmp_path, words, vocabulary, misheard)

    assert segment.text == expected_text
    assert [correction["term"] for correction in segment.corrections] == expected_terms


def test_a_merged_word_keeps_the_lowest_confidence_of_its_parts(monkeypatch, tmp_path):
    words = [Word(0.1, 0.5, " Gar", 0.9), Word(0.31, 0.4, " rah,", 0.7)]

    segment = _processed_segment(monkeypatch, tmp_path, words, "Vocabulary: Garrah")

    assert segment.confidence == 0.7
    assert segment.corrections[0]["heard"] == "Gar rah,"


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
