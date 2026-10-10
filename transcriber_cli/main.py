"""Command-line entry point: `python -m transcriber_cli <command>`."""

import argparse
import json
import os
import re
import sys
import time

from . import suspects
from .client import Api, ApiError
from .handles import resolve_meeting, resolve_note, resolve_segment, resolve_speaker
from .render import (
    clock, meeting_header, note_line, parse_clock, segment_line, speaker_line, word_line,
)

REPROCESS_KINDS = ("rediarize", "reidentify", "reapply-vocabulary")
BINARY_FORMATS = ("docx", "pdf")
EXIT_SERVER_DOWN = 2
EXIT_TIMEOUT = 3


def emit(args, data, text_lines):
    """Print the raw API JSON under --json, else the text lines."""
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        for line in text_lines:
            print(line)


def load_meeting(api, handle) -> dict:
    """The full Meeting (Speakers, Segments) for any Meeting handle."""
    return api.get(f"/api/meetings/{resolve_meeting(api, handle)['id']}")


# --- commands -------------------------------------------------------------


def cmd_health(api, args):
    health = api.get("/api/health")
    lines = [str(health.get("status"))]
    for name, value in health.items():
        if name not in ("status", "disk_free_gb") and value != "ok":
            lines.append(f"{name}: {value}")
    emit(args, health, lines)
    return 0


def cmd_list(api, args):
    meetings = api.get("/api/meetings")
    lines = [
        f"{m['id'][:8]} {m['status']} {clock(m.get('duration'))} "
        f"speakers={m.get('speaker_count') or 0} segments={m.get('segment_count') or 0} {m['title']}"
        for m in meetings
    ]
    emit(args, meetings, lines)
    return 0


def _queued(api, args, meeting_id, kind):
    job = api.post(f"/api/meetings/{meeting_id}/{kind}")
    emit(args, job, [f"queued {job['job_type']} job {job['id'][:8]} for Meeting {meeting_id[:8]}"])
    return 0


def cmd_upload(api, args):
    if not os.path.isfile(args.file):
        raise ApiError(400, f"File not found: {args.file}")
    if args.wait and not args.process:
        raise ApiError(400, "--wait needs --process")
    files = {"file": args.file}
    if args.system:
        if not os.path.isfile(args.system):
            raise ApiError(400, f"File not found: {args.system}")
        files["system_file"] = args.system
    options = {
        "participants": args.participants,
        "vocabulary": args.vocabulary,
        "preset_id": args.preset,
        "min_speakers": args.min_speakers,
        "max_speakers": args.max_speakers,
    }
    fields = {"title": args.title}
    fields.update({k: str(v) for k, v in options.items() if v is not None})
    meeting = api.upload("/api/meetings", fields, files)
    emit(args, meeting, [meeting["id"]])
    if args.process:
        _queued(api, args, meeting["id"], "process")
        if args.wait:
            return _wait(api, args, meeting["id"], timeout=None, interval=2.0)
    return 0


def cmd_process(api, args):
    meeting = resolve_meeting(api, args.meeting)
    code = _queued(api, args, meeting["id"], "process")
    if args.wait:
        return _wait(api, args, meeting["id"], timeout=None, interval=2.0)
    return code


def cmd_reprocess(api, args):
    meeting = resolve_meeting(api, args.meeting)
    code = _queued(api, args, meeting["id"], args.kind)
    if args.wait:
        return _wait(api, args, meeting["id"], timeout=None, interval=2.0)
    return code


def _wait(api, args, meeting_id, timeout, interval):
    started = time.monotonic()
    last = None
    while True:
        jobs = api.get(f"/api/meetings/{meeting_id}/jobs")
        if not jobs:
            raise ApiError(404, "This Meeting has no Jobs")
        job = jobs[0]
        shown = (round(job.get("progress") or 0), job.get("current_step"))
        if shown != last and not args.json:
            last = shown
            print(f"{shown[0]}% {shown[1] or job['status']}")
        if job["status"] == "completed":
            if args.json:
                print(json.dumps(job, ensure_ascii=False, indent=2))
            return 0
        if job["status"] == "failed":
            if args.json:
                print(json.dumps(job, ensure_ascii=False, indent=2))
            else:
                print(f"failed: {job.get('error') or 'unknown error'}")
            return 1
        if timeout is not None and time.monotonic() - started >= timeout:
            print(f"timed out after {timeout:g}s; Job still {job['status']}", file=sys.stderr)
            return EXIT_TIMEOUT
        time.sleep(interval)


def cmd_wait(api, args):
    meeting = resolve_meeting(api, args.meeting)
    return _wait(api, args, meeting["id"], args.timeout, args.interval)


def _overlaps(seg, start, end):
    return (end is None or seg["start_time"] < end) and (start is None or seg["end_time"] > start)


def cmd_show(api, args):
    meeting = load_meeting(api, args.meeting)
    segments = meeting["segments"]
    if args.speaker:
        speaker = resolve_speaker(meeting, args.speaker)
        segments = [s for s in segments if s["speaker_id"] == speaker["id"]]
    segments = [s for s in segments if _overlaps(s, args.start, args.end)]
    if args.grep is not None:
        try:
            pattern = re.compile(args.grep, re.IGNORECASE)
        except re.error as error:
            raise ApiError(400, f"invalid --grep pattern: {error}")
        segments = [s for s in segments if pattern.search(s["text"] or "")]
    if args.limit is not None:
        segments = segments[: args.limit]
    filtered = any(
        value is not None for value in (args.speaker, args.start, args.end, args.grep, args.limit)
    )
    lines = []
    if not filtered:
        lines = meeting_header(meeting)
        lines += ["", *(speaker_line(s) for s in meeting["speakers"]), ""]
    lines += [segment_line(s) for s in segments]
    emit(args, {**meeting, "segments": segments}, lines)
    return 0


def _is_unnamed(speaker):
    """No Voice Profile matched it and no person named it; the dual-track HOST starts as 'You'."""
    return speaker.get("identified_by") in (None, "host_track") and speaker["label"] != "UNKNOWN"


def cmd_speakers(api, args):
    meeting = load_meeting(api, args.meeting)
    speakers = [s for s in meeting["speakers"] if not args.unnamed or _is_unnamed(s)]
    samples = args.samples if args.samples is not None else (3 if args.unnamed else 0)
    lines = []
    for speaker in speakers:
        lines.append(speaker_line(speaker))
        if samples:
            own = [s for s in meeting["segments"] if s["speaker_id"] == speaker["id"]]
            own.sort(key=lambda s: s["end_time"] - s["start_time"], reverse=True)
            lines += [f"  {segment_line(s)}" for s in own[:samples]]
    emit(args, speakers, lines)
    return 0


def cmd_words(api, args):
    meeting = resolve_meeting(api, args.meeting)
    words = api.get(f"/api/meetings/{meeting['id']}/words", start=args.start, end=args.end)
    if args.below is not None:
        words = [
            w for w in words
            if w.get("confidence") is not None and w["confidence"] < args.below
        ]
    emit(args, words, [word_line(w) for w in words])
    return 0


def _section(title, entries, limit):
    """Heading plus capped entries; nothing when there are no entries."""
    if not entries:
        return []
    shown = entries if limit is None else entries[:limit]
    note = f" (showing {len(shown)} of {len(entries)})" if len(shown) < len(entries) else ""
    return [f"{title}{note}", *(f"  {entry}" for entry in shown)]


CUT_TEXT_CHARS = 60  # how much of each side of a cut sentence `suspects` shows


def _order_range(first, last):
    return f"#{first}" if first == last else f"#{first}-#{last}"


def cmd_suspects(api, args):
    meeting = load_meeting(api, args.meeting)
    segments = meeting["segments"]
    by_order = {s["order"]: s for s in segments}
    words = api.get(f"/api/meetings/{meeting['id']}/words")

    windows = suspects.repetition_windows(segments)
    passages = suspects.low_confidence_passages(words, segments, args.below)
    corrected = suspects.corrected_segments(segments)
    cuts = suspects.speaker_cuts(segments)

    def cut_entry(cut):
        first, second = by_order[cut["first_order"]], by_order[cut["second_order"]]
        first_text, second_text = first["text"].strip(), second["text"].strip()
        if len(first_text) > CUT_TEXT_CHARS:
            first_text = "…" + first_text[-CUT_TEXT_CHARS:]
        if len(second_text) > CUT_TEXT_CHARS:
            second_text = second_text[:CUT_TEXT_CHARS] + "…"
        first_who = first.get("speaker_name") or first.get("speaker_label") or "?"
        second_who = second.get("speaker_name") or second.get("speaker_label") or "?"
        return (
            f'#{first["order"]} {clock(first["start_time"])} {first_who}: "{first_text}" | '
            f'#{second["order"]} {second_who}: "{second_text}"'
        )

    def passage_entry(passage):
        weak = ", ".join(f"{text.strip()} {confidence:.2f}" for text, confidence in passage["words"])
        return f"{segment_line(by_order[passage['order']])} | weak: {weak}"

    fixes = [
        f"#{s['order']} {clock(s['start_time'])} {fix['heard'].strip()}->{fix['term'].strip()} "
        f"(rule {fix.get('rule')})"
        for s in corrected for fix in s["corrections"]
    ]
    lines = []
    for title, entries in (
        ("REPEATED (possible hallucination over silence)", [
            f"{clock(w['start'])}-{clock(w['end'])} {_order_range(w['first_order'], w['last_order'])} "
            f'x{w["count"]} "{w["text"]}"' for w in windows
        ]),
        ("LOW-CONFIDENCE PASSAGES (worst first)", [passage_entry(p) for p in passages]),
        ("CORRECTED BY VOCABULARY", fixes),
        ("SENTENCE CUT BY A SPEAKER CHANGE", [cut_entry(c) for c in cuts]),
    ):
        lines += _section(title, entries, args.limit)
    emit(args, {
        "repeated": windows,
        "low_confidence_passages": passages,
        "corrected_segments": corrected,
        "speaker_cuts": cuts,
    }, lines)
    return 0


def cmd_rename(api, args):
    meeting = load_meeting(api, args.meeting)
    speaker = resolve_speaker(meeting, args.speaker)
    updated = api.put(f"/api/speakers/{speaker['id']}", json={"display_name": args.name})
    lines = [speaker_line(updated)]
    data = updated
    if args.save_profile:
        profile = api.post(
            "/api/speaker-profiles/save-from-speaker",
            json={"speaker_id": speaker["id"], "meeting_id": meeting["id"], "name": args.name},
        )
        lines.append(f"voice profile saved: {args.name}")
        data = {"speaker": updated, "voice_profile": profile}
    emit(args, data, lines)
    return 0


def _add_speaker(api, meeting_id, name) -> dict:
    return api.post(f"/api/meetings/{meeting_id}/speakers", json={"display_name": name})


def cmd_add_speaker(api, args):
    meeting = resolve_meeting(api, args.meeting)
    speaker = _add_speaker(api, meeting["id"], args.name)
    emit(args, speaker, [speaker_line(speaker)])
    return 0


def cmd_merge(api, args):
    meeting = load_meeting(api, args.meeting)
    source = resolve_speaker(meeting, args.source)
    target = resolve_speaker(meeting, args.target)
    merged = api.post("/api/speakers/merge", json={"source_id": source["id"], "target_id": target["id"]})
    emit(args, merged, [speaker_line(merged)])
    return 0


def cmd_edit(api, args):
    meeting = load_meeting(api, args.meeting)
    segment = resolve_segment(meeting, args.segment)
    updated = api.put(f"/api/segments/{segment['id']}", json={"text": args.text, "learn": args.learn})
    emit(args, updated, [segment_line(updated)])
    return 0


def cmd_revert(api, args):
    meeting = load_meeting(api, args.meeting)
    segment = resolve_segment(meeting, args.segment)
    updated = api.post(f"/api/segments/{segment['id']}/revert")
    emit(args, updated, [segment_line(updated)])
    return 0


NEW_SPEAKER_PREFIX = "new:"


def cmd_assign(api, args):
    meeting = load_meeting(api, args.meeting)
    segment = resolve_segment(meeting, args.segment)
    if args.speaker.startswith(NEW_SPEAKER_PREFIX):
        name = args.speaker[len(NEW_SPEAKER_PREFIX):].strip()
        if not name:
            raise ApiError(400, "new: needs a name, e.g. new:Carla")
        speaker_id = _add_speaker(api, meeting["id"], name)["id"]
    else:
        speaker_id = resolve_speaker(meeting, args.speaker)["id"]
    updated = api.put(f"/api/segments/{segment['id']}/speaker", json={"speaker_id": speaker_id})
    emit(args, updated, [segment_line(updated)])
    return 0


PUNCTUATION = ".,;:!?…\"'()[]"


def _heard(text: str) -> str:
    return text.strip().strip(PUNCTUATION + " ").casefold()


def _segment_words(api, meeting, segment) -> list:
    """The Words the Transcriber heard inside the Segment."""
    words = api.get(
        f"/api/meetings/{meeting['id']}/words",
        start=segment["start_time"], end=segment["end_time"],
    )
    return [
        word for word in words
        if word["start"] >= segment["start_time"] - 1e-6 and word["end"] <= segment["end_time"] + 1e-6
    ]


def _cut_before(segment, inside, phrase) -> float:
    """The start of the Word where `phrase` begins among the Segment's Words, as the Transcriber heard it."""
    heard = [(index, _heard(word["text"]), word) for index, word in enumerate(inside)]
    heard = [entry for entry in heard if entry[1]]
    wanted = [token for token in map(_heard, phrase.split()) if token]
    handle = f"#{segment['order']}"
    matches = [
        heard[position][2] for position in range(len(heard) - len(wanted) + 1)
        if wanted and heard[position][0] >= 1
        and [entry[1] for entry in heard[position:position + len(wanted)]] == wanted
    ]
    if not matches:
        raise ApiError(400, (
            f"'{phrase}' is not among {handle}'s Words as heard; "
            f"see `words M --from .. --to ..` or use --at"
        ))
    if len(matches) > 1:
        where = ", ".join(f"{clock(word['start'])} (--at {word['start']:g})" for word in matches)
        raise ApiError(400, f"'{phrase}' occurs {len(matches)} times in {handle}: {where}; choose one with --at")
    return matches[0]["start"]


def cmd_split(api, args):
    meeting = load_meeting(api, args.meeting)
    segment = resolve_segment(meeting, args.segment)
    at = args.at if args.at is not None else _cut_before(segment, _segment_words(api, meeting, segment), args.before)
    body = {"at": at}
    if args.speaker is not None:
        if args.speaker.startswith(NEW_SPEAKER_PREFIX):
            name = args.speaker[len(NEW_SPEAKER_PREFIX):].strip()
            if not name:
                raise ApiError(400, "new: needs a name, e.g. new:Carla")
            body["speaker_id"] = _add_speaker(api, meeting["id"], name)["id"]
        else:
            body["speaker_id"] = resolve_speaker(meeting, args.speaker)["id"]
    result = api.post(f"/api/segments/{segment['id']}/split", json=body)
    emit(args, result, [
        *(segment_line(half) for half in result["segments"]),
        f"Segments after #{segment['order']} are renumbered (+1).",
    ])
    return 0


def cmd_unsplit(api, args):
    meeting = load_meeting(api, args.meeting)
    segment = resolve_segment(meeting, args.segment)
    joined = api.post(f"/api/segments/{segment['id']}/unsplit")
    emit(args, joined, [
        segment_line(joined),
        f"Segments after #{segment['order']} are renumbered (-1).",
    ])
    return 0


def cmd_notes(api, args):
    meeting = load_meeting(api, args.meeting)
    notes = api.get(f"/api/meetings/{meeting['id']}/notes", status=args.status)
    emit(args, notes, [note_line(n, meeting["segments"]) for n in notes])
    return 0


def _leave_note(api, args, meeting, anchor, kind, body, payload=None):
    """Create an agent's Review Note anchored at the Segment's time range."""
    note = api.post(f"/api/meetings/{meeting['id']}/notes", json={
        "start_time": anchor["start_time"], "end_time": anchor["end_time"],
        "kind": kind, "body": body, "author": "agent", "payload": payload,
    })
    emit(args, note, [note_line(note, meeting["segments"])])
    return 0


def cmd_ask(api, args):
    meeting = load_meeting(api, args.meeting)
    return _leave_note(api, args, meeting, resolve_segment(meeting, args.segment), "question", args.question)


def cmd_note(api, args):
    meeting = load_meeting(api, args.meeting)
    return _leave_note(api, args, meeting, resolve_segment(meeting, args.segment), "comment", args.comment)


def cmd_suggest(api, args):
    meeting = load_meeting(api, args.meeting)
    segment = resolve_segment(meeting, args.segment)
    payload = {"expected_text": segment["text"], "proposed_text": args.text}
    return _leave_note(api, args, meeting, segment, "text", args.why, payload)


def cmd_suggest_name(api, args):
    meeting = load_meeting(api, args.meeting)
    speaker = resolve_speaker(meeting, args.speaker)
    payload = {"label": speaker["label"], "name": args.name}
    return _leave_note(api, args, meeting, resolve_segment(meeting, args.at), "speaker_name", args.why, payload)


def cmd_suggest_move(api, args):
    meeting = load_meeting(api, args.meeting)
    segment = resolve_segment(meeting, args.segment)
    if args.speaker.startswith(NEW_SPEAKER_PREFIX):
        name = args.speaker[len(NEW_SPEAKER_PREFIX):].strip()
        if not name:
            raise ApiError(400, "new: needs a name, e.g. new:Carla")
        payload = {"new_name": name}
    else:
        payload = {"target_label": resolve_speaker(meeting, args.speaker)["label"]}
    return _leave_note(api, args, meeting, segment, "speaker_move", args.why, payload)


PREVIEW_WORDS = 5


def cmd_suggest_split(api, args):
    meeting = load_meeting(api, args.meeting)
    segment = resolve_segment(meeting, args.segment)
    inside = _segment_words(api, meeting, segment)
    if args.before is not None:
        at = _cut_before(segment, inside, args.before)
    elif len(inside) < 2:
        raise ApiError(400, f"#{segment['order']} has no Word boundary to cut at")
    else:  # the same snap the split route makes: the nearest Word start after the first Word
        at = min(inside[1:], key=lambda word: abs(word["start"] - args.at))["start"]
    second_half = [word for word in inside if word["start"] >= at - 1e-6]
    payload = {"at": at, "preview": " ".join(word["text"].strip() for word in second_half[:PREVIEW_WORDS])}
    if args.speaker is not None:
        if args.speaker.startswith(NEW_SPEAKER_PREFIX):
            name = args.speaker[len(NEW_SPEAKER_PREFIX):].strip()
            if not name:
                raise ApiError(400, "new: needs a name, e.g. new:Carla")
            payload["new_name"] = name
        else:
            payload["target_label"] = resolve_speaker(meeting, args.speaker)["label"]
    return _leave_note(api, args, meeting, segment, "split", args.why, payload)


def cmd_suggest_merge(api, args):
    meeting = load_meeting(api, args.meeting)
    payload = {
        "source_label": resolve_speaker(meeting, args.source)["label"],
        "target_label": resolve_speaker(meeting, args.target)["label"],
    }
    return _leave_note(api, args, meeting, resolve_segment(meeting, args.at), "speaker_merge", args.why, payload)


def cmd_close(api, args):
    meeting = load_meeting(api, args.meeting)
    note = resolve_note(meeting, args.note)
    closed = api.post(f"/api/notes/{note['id']}/done", json={"reply": args.reply})
    emit(args, closed, [note_line(closed, meeting["segments"])])
    return 0


def cmd_set(api, args):
    fields = {"title": args.title, "participants": args.participants, "vocabulary": args.vocabulary}
    fields = {name: value for name, value in fields.items() if value is not None}
    if not fields:
        raise ApiError(400, "nothing to set; pass --title, --participants or --vocabulary")
    meeting = resolve_meeting(api, args.meeting)
    updated = api.put(f"/api/meetings/{meeting['id']}", json=fields)
    emit(args, updated, meeting_header(updated))
    return 0


def cmd_export(api, args):
    if args.format in BINARY_FORMATS and not args.out:
        raise ApiError(400, f"{args.format} is a binary format; pass --out PATH")
    meeting = resolve_meeting(api, args.meeting)
    content = api.raw(f"/api/meetings/{meeting['id']}/export", format=args.format)
    if args.out:
        with open(args.out, "wb") as handle:
            handle.write(content)
        print(f"wrote {len(content)} bytes to {args.out}")
    else:
        sys.stdout.write(content.decode("utf-8-sig"))
    return 0


# --- parser ---------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="transcriber_cli",
        description="Operate the local Transcriber app: run Meetings and read them in compact text. "
        "Meeting handles: a full id, a unique id prefix (4+ characters), or an exact title. "
        "Segment handles: #<order>. Speaker handles: a label (SPEAKER_01), a name, or an id prefix. "
        "Times: SS, MM:SS, or H:MM:SS.",
    )
    parser.add_argument("--json", action="store_true", default=False,
                        help="print the API's JSON instead of text (--from/--to/--speaker/--grep/--limit still filter Segments)")
    sub = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    def command(name, func, help, meeting=True):
        p = sub.add_parser(name, help=help, description=help)
        p.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help=argparse.SUPPRESS)
        p.set_defaults(func=func)
        if meeting:
            p.add_argument("meeting", metavar="M", help="Meeting handle")
        return p

    command("health", cmd_health, "check that the app and its database are up", meeting=False)
    command("list", cmd_list, "one line per Meeting", meeting=False)

    p = command("upload", cmd_upload, "add a Meeting from an audio file", meeting=False)
    p.add_argument("file", metavar="FILE")
    p.add_argument("--title", required=True)
    p.add_argument("--system", metavar="FILE", help="separate system-audio track (dual-track)")
    p.add_argument("--participants", help="attendee names, comma-separated")
    p.add_argument("--vocabulary", help="domain terms the Transcriber should spell correctly")
    p.add_argument("--preset", metavar="ID")
    p.add_argument("--min-speakers", type=int)
    p.add_argument("--max-speakers", type=int)
    p.add_argument("--process", action="store_true", help="start processing after the upload")
    p.add_argument("--wait", action="store_true", help="with --process, block until the Job ends")

    p = command("process", cmd_process, "start processing a Meeting")
    p.add_argument("--wait", action="store_true", help="block until the Job ends")

    p = command("reprocess", cmd_reprocess, "run one stage of Reprocessing again")
    p.add_argument("kind", choices=REPROCESS_KINDS)
    p.add_argument("--wait", action="store_true", help="block until the Job ends")

    p = command("wait", cmd_wait,
                "block until the newest Job ends (exit 0 completed, 1 failed, 3 timeout)")
    p.add_argument("--timeout", type=float, metavar="SECONDS", help="give up after this long (default: never)")
    p.add_argument("--interval", type=float, default=2.0, metavar="SECONDS")

    p = command("show", cmd_show,
                "the Segments, one line each; a whole-Meeting read (no filter) starts with the header and Speakers")
    p.add_argument("--from", dest="start", type=parse_clock, metavar="T", help="Segments ending after T")
    p.add_argument("--to", dest="end", type=parse_clock, metavar="T", help="Segments starting before T")
    p.add_argument("--speaker", metavar="S")
    p.add_argument("--grep", metavar="PATTERN",
                   help="only Segments whose text matches this case-insensitive regular expression")
    p.add_argument("--limit", type=int, metavar="N", help="at most N Segments")

    p = command("speakers", cmd_speakers, "one line per Speaker")
    p.add_argument("--unnamed", action="store_true",
                   help="only Speakers nobody has named (not UNKNOWN); includes the dual-track HOST, "
                   "which starts as 'You'")
    p.add_argument("--samples", type=int, metavar="N",
                   help="also print each Speaker's N longest Segments (default 0; 3 with --unnamed)")

    p = command("words", cmd_words, "Words as the Transcriber heard them, with confidence")
    p.add_argument("--from", dest="start", type=parse_clock, required=True, metavar="T")
    p.add_argument("--to", dest="end", type=parse_clock, required=True, metavar="T")
    p.add_argument("--below", type=float, metavar="C", help="only Words with confidence under C")

    p = command("suspects", cmd_suspects,
                "passages worth a second look: repeated sentences, Segments holding weak Words (worst first), Vocabulary fixes, sentences cut by a Speaker change")
    p.add_argument("--below", type=float, default=suspects.WEAK_WORD, metavar="C",
                   help=f"Word confidence threshold (default {suspects.WEAK_WORD})")
    p.add_argument("--limit", type=int, default=40, metavar="N", help="at most N entries per section (default 40)")

    p = command("rename", cmd_rename, "name a Speaker (the name sticks across Re-identify)")
    p.add_argument("speaker", metavar="SPEAKER")
    p.add_argument("name", metavar="NAME")
    p.add_argument("--save-profile", action="store_true",
                   help="also save the voice as a Voice Profile, so future Meetings name it")

    p = command("add-speaker", cmd_add_speaker, "add a Speaker the Diarizer missed (label MANUAL_n)")
    p.add_argument("name", metavar="NAME")

    p = command("merge", cmd_merge, "move all of SOURCE's Segments to TARGET and delete SOURCE")
    p.add_argument("source", metavar="SOURCE")
    p.add_argument("target", metavar="TARGET")

    p = command("edit", cmd_edit, "replace a Segment's text")
    p.add_argument("segment", metavar="SEG", help="Segment handle, #<order>")
    p.add_argument("text", metavar="TEXT")
    p.add_argument("--learn", action="store_true",
                   help="teach Vocabulary the correction (only for fixes the user confirmed)")

    p = command("revert", cmd_revert, "undo a Segment's text edit")
    p.add_argument("segment", metavar="SEG", help="Segment handle, #<order>")

    p = command("assign", cmd_assign, "move a Segment to another Speaker (new:NAME adds one first)")
    p.add_argument("segment", metavar="SEG", help="Segment handle, #<order>")
    p.add_argument("speaker", metavar="SPEAKER")

    p = command("split", cmd_split,
                "cut a Segment in two where the Diarizer joined two people; "
                "the cut survives every Reprocessing, and later Segment handles shift by one")
    p.add_argument("segment", metavar="SEG", help="Segment handle, #<order>")
    where = p.add_mutually_exclusive_group(required=True)
    where.add_argument("--at", type=parse_clock, metavar="T",
                       help="cut at the Word starting nearest this time (seconds or mm:ss)")
    where.add_argument("--before", metavar="WORDS",
                       help="cut before these first Word(s) of the second half, as the Transcriber heard them")
    p.add_argument("--speaker", metavar="SPEAKER",
                   help="give the second half to this Speaker (new:NAME adds one); "
                        "a reassignment like assign: re-applied on Re-identify and Reapply Vocabulary, "
                        "dropped on Re-diarize")

    p = command("unsplit", cmd_unsplit,
                "join a Segment with the next one when a Split lies between them; later handles shift by one")
    p.add_argument("segment", metavar="SEG", help="Segment handle, #<order>")

    p = command("notes", cmd_notes, "the Meeting's Review Notes, one line each (answered ones are the user's replies)")
    p.add_argument("--status", choices=("open", "answered", "resolved", "all"), default="all")

    p = command("ask", cmd_ask, "leave a question for the user at a Segment")
    p.add_argument("segment", metavar="SEG", help="Segment handle, #<order>")
    p.add_argument("question", metavar="QUESTION")

    p = command("note", cmd_note, "leave a comment at a Segment")
    p.add_argument("segment", metavar="SEG", help="Segment handle, #<order>")
    p.add_argument("comment", metavar="COMMENT")

    p = command("suggest", cmd_suggest,
                "propose new text for a Segment; the user accepts it on the Meeting page (which teaches Vocabulary)")
    p.add_argument("segment", metavar="SEG", help="Segment handle, #<order>")
    p.add_argument("text", metavar="TEXT")
    p.add_argument("--why", required=True, metavar="REASON")

    p = command("suggest-name", cmd_suggest_name, "propose a name for a Speaker; accepting it also saves the Voice Profile")
    p.add_argument("speaker", metavar="SPEAKER")
    p.add_argument("name", metavar="NAME")
    p.add_argument("--at", required=True, metavar="SEG", help="the Segment that is the evidence, #<order>")
    p.add_argument("--why", required=True, metavar="REASON")

    p = command("suggest-move", cmd_suggest_move, "propose moving a Segment to another Speaker (new:NAME for a new one)")
    p.add_argument("segment", metavar="SEG", help="Segment handle, #<order>")
    p.add_argument("speaker", metavar="SPEAKER")
    p.add_argument("--why", required=True, metavar="REASON")

    p = command("suggest-split", cmd_suggest_split,
                "propose cutting a Segment in two when the text does not show where the second person starts; "
                "the user accepts it on the Meeting page")
    p.add_argument("segment", metavar="SEG", help="Segment handle, #<order>")
    where = p.add_mutually_exclusive_group(required=True)
    where.add_argument("--at", type=parse_clock, metavar="T",
                       help="cut at the Word starting nearest this time (seconds or mm:ss)")
    where.add_argument("--before", metavar="WORDS",
                       help="cut before these first Word(s) of the second half, as the Transcriber heard them")
    p.add_argument("--speaker", metavar="SPEAKER",
                   help="give the second half to this Speaker (new:NAME adds one when the user accepts)")
    p.add_argument("--why", required=True, metavar="REASON")

    p = command("suggest-merge", cmd_suggest_merge, "propose merging SOURCE into TARGET")
    p.add_argument("source", metavar="SOURCE")
    p.add_argument("target", metavar="TARGET")
    p.add_argument("--at", required=True, metavar="SEG", help="the Segment that is the evidence, #<order>")
    p.add_argument("--why", required=True, metavar="REASON")

    p = command("close", cmd_close, "close an answered question or a comment once acted on")
    p.add_argument("note", metavar="NOTE", help="Note handle: n:<id8>, an id prefix (4+ characters), or the id")
    p.add_argument("--reply", metavar="TEXT", help="a short reply to the user")

    p = command("set", cmd_set,"change the Meeting's title, participants, or vocabulary")
    p.add_argument("--title")
    p.add_argument("--participants", help="attendee names, comma-separated")
    p.add_argument("--vocabulary", help="domain terms the Transcriber should spell correctly")

    p = command("export", cmd_export, "download the transcript (docx and pdf need --out)")
    p.add_argument("--format", required=True, choices=("srt", "vtt", "txt", "json", "md", "docx", "pdf"))
    p.add_argument("--out", metavar="PATH")
    return parser


def main(argv=None, api: Api | None = None) -> int:
    args = build_parser().parse_args(argv)
    api = api or Api()
    try:
        return args.func(api, args)
    except ApiError as error:
        print(f"error: {error}", file=sys.stderr)
        return EXIT_SERVER_DOWN if error.status == 0 else 1
