# An agent may operate the local API

**Status**: accepted

The user may hand a Meeting to a coding agent (Claude Code, Codex, or an agent
running a local model) that drives this app through its HTTP API: uploading and
processing Meetings, reading the transcript, naming Speakers, and correcting
Segments. The agent reads transcript text, and if its model is hosted, that text
leaves the machine.

This does not contradict ADR-0001. ADR-0001 constrains the app: no Engine, Job,
or route sends Meeting data anywhere, and that stays true. An agent is a client
the user chose to run, like copying an export into a chat. The app never calls
an agent, never ships an API key, and never depends on one.

## Consequences

- The agent interface is the HTTP API plus a stdlib-only CLI over it
  (`transcriber_cli`). Nothing in the app imports an LLM SDK.
- The CLI works the same against any agent, so a user who wants ADR-0001's
  guarantee end to end can run the workflow with a local model.
- Agent text edits do not teach Vocabulary by default: the agent cannot hear the
  audio, so its corrections are guesses until the user confirms them.
- Agent naming complements Voice Profile matching (ADR-0002, point 4): the agent
  names only the Speakers no Voice Profile matched, and saving a Voice Profile
  stays an explicit step so the next Meeting is named from the voice.
- ADR-0002 still governs any LLM feature built *into* the app.
