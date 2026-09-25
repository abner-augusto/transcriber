import json

from models import Meeting, MeetingStatus, Segment
from transcript.vocabulary_correction import MisheardForm

from bench.vocabulary_correction import score_meeting, write_report


def _meeting(meeting_id, vocabulary, *, heard="Galo", edited="Garrah"):
    return Meeting(
        id=meeting_id,
        title="PRIVATE TITLE",
        status=MeetingStatus.COMPLETED,
        vocabulary=vocabulary,
        raw_transcription={
            "engine": "parakeet.cpp",
            "words": [{"start": 0.1, "end": 0.5, "text": f" {heard}"}],
        },
        raw_diarization={
            "engine": "pyannote",
            "turns": [{"start": 0.0, "end": 1.0, "speaker": "SPEAKER_00"}],
        },
    ), Segment(
        meeting_id=meeting_id,
        start_time=0.1,
        end_time=0.5,
        text=edited,
        original_text=heard,
        order=0,
        is_edited=True,
    )


def test_bench_counts_hits_false_changes_and_misses_without_serializing_transcript_text(tmp_path):
    hit_meeting, hit_edit = _meeting("meeting-hit", "Speakers: Garrah")
    false_meeting, false_edit = _meeting("meeting-false", "Vocabulary: Gallo")

    hit = score_meeting(
        hit_meeting, [hit_edit], [MisheardForm("Galo", "Garrah", 1)]
    )
    false_and_miss = score_meeting(false_meeting, [false_edit], [])
    output = tmp_path / "report.json"
    report = write_report([hit, false_and_miss], output)

    assert report["totals"] == {"hits": 1, "false_changes": 1, "misses": 1}
    assert [item["meeting_id"] for item in report["meetings"]] == [
        "meeting-hit", "meeting-false"
    ]
    serialized = output.read_text(encoding="utf-8")
    assert "PRIVATE TITLE" not in serialized
    assert all(term not in serialized for term in ("Galo", "Garrah", "Gallo"))
    assert set(json.loads(serialized)["meetings"][0]) == {
        "meeting_id", "engine", "hits", "false_changes", "misses"
    }


def test_bench_counts_accent_only_manual_edit_as_a_hit():
    meeting, edited = _meeting(
        "meeting-accent", "Vocabulary: João", heard="Joao", edited="João"
    )
    count = score_meeting(meeting, [edited], [])

    assert (count.hits, count.false_changes, count.misses) == (1, 0, 0)


def test_bench_scores_each_meeting_only_with_forms_learned_elsewhere(tmp_path, monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    import bench.vocabulary_correction as bench
    from database import Base
    from models import VocabularyEntry

    engine = create_engine(f"sqlite:///{tmp_path / 'bench.db'}")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    with sessions() as db:
        for meeting_id in ("meeting-a", "meeting-b"):
            db.add_all(_meeting(meeting_id, ""))
        # What the app learned from those two edits: the form was heard twice,
        # so it is eligible everywhere, including in the Meetings it came from.
        db.add(VocabularyEntry(term="Garrah", misheard_as=[{"form": "Galo", "count": 2}]))
        db.commit()
    monkeypatch.setattr(bench, "SessionLocal", sessions)

    report = bench.run(tmp_path / "report.json")

    # Each Meeting sees the form once, from the other Meeting: not enough to use it.
    assert report["totals"] == {"hits": 0, "false_changes": 0, "misses": 2}
    engine.dispose()
