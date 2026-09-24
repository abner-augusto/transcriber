"""Words as a Meeting stores them."""

from engines import Word


def words_from_stored(raw) -> list[Word]:
    """Words out of a Meeting's raw_transcription, whatever era wrote it.

    Meetings transcribed before the Transcriber port stored whisper's coarse segments
    as a bare list. Each is read back as one long Word — it has a start, an end and
    text, which is all a Word is — with the leading space the Word contract wants.
    """
    if not raw:
        return []
    if isinstance(raw, dict):
        return [Word.from_dict(w) for w in raw.get("words", [])]

    return [
        Word(
            start=float(item["start"]),
            end=float(item["end"]),
            text=" " + item["text"].strip(),
            confidence=item.get("confidence"),
            alignment_score=item.get("alignment_score"),
        )
        for item in raw
        if item.get("text", "").strip()
    ]
