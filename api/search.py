import re

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text as sa_text
from sqlalchemy.orm import Session

from database import get_db

router = APIRouter(prefix="/api", tags=["search"])


def _fts_prefix_query(query: str) -> str:
    """Build an AND query of safely quoted FTS5 token prefixes."""
    terms = re.findall(r"[^\W_]+", query, flags=re.UNICODE)
    return " AND ".join(f'"{term}"*' for term in terms)


@router.get("/search")
def search_segments(
    q: str = Query(..., min_length=1, max_length=200),
    db: Session = Depends(get_db),
):
    """Search segment text with accent-insensitive FTS5 and prefix matching."""
    fts_query = _fts_prefix_query(q)
    if not fts_query:
        return []

    results = db.execute(
        sa_text("""
            SELECT
                s.id, s.meeting_id, s.start_time, s.end_time, s.text, s."order",
                m.title AS meeting_title,
                sp.display_name AS speaker_name,
                sp.color AS speaker_color,
                bm25(segments_fts) AS rank
            FROM segments_fts
            JOIN segments s ON s.rowid = segments_fts.rowid
            JOIN meetings m ON m.id = s.meeting_id
            LEFT JOIN speakers sp ON sp.id = s.speaker_id
            WHERE segments_fts MATCH :fts_query
            ORDER BY rank ASC, m.created_at DESC, s."order"
            LIMIT 100
        """),
        {"fts_query": fts_query},
    )

    meetings_map: dict[str, dict] = {}
    for row in results.fetchall():
        mid = row.meeting_id
        if mid not in meetings_map:
            meetings_map[mid] = {
                "meeting_id": mid,
                "meeting_title": row.meeting_title,
                "segments": [],
            }
        meetings_map[mid]["segments"].append({
            "id": row.id,
            "start_time": row.start_time,
            "end_time": row.end_time,
            "text": row.text,
            "order": row.order,
            "speaker_name": row.speaker_name,
            "speaker_color": row.speaker_color,
        })

    return list(meetings_map.values())
