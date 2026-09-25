# 01 - Queue Meetings from New Meeting and Process from Home

**What to build:** Let the user add several Meetings through the New transcription flow and start their transcription together from the home page. Each new Meeting keeps its audio, participants, vocabulary, speaker limits, and selected Preset, but waits in a persistent queue until the user starts it. Process queued Meetings one at a time in the order they were added.

**Current behavior:** `POST /api/meetings` saves a Meeting as `uploaded`; the home page then opens its detail page, where the user can start processing individually. There is no queue or home page action for starting multiple Meetings.

**Blocked by:** None — can start immediately.

**Status:** ready-for-agent

- [ ] The New transcription dialog adds a Meeting to the queue without starting a Job and returns the user to the home page, where the queued Meeting is visible.
- [ ] Queue membership and order persist across page reloads and application restarts. The UI distinguishes queued Meetings from Meetings that are merely uploaded, processing, completed, or failed.
- [ ] The home page shows the number of queued Meetings and a button to process them all. The button is unavailable when the queue is empty or a queue run is already active.
- [ ] Starting the queue processes each queued Meeting once, in the order added, with at most one queued Meeting processing at a time. Repeated clicks or concurrent requests do not create duplicate Jobs.
- [ ] A failed Meeting is marked failed and does not stop later queued Meetings. The home page shows each Meeting's current status and any actionable failure.
- [ ] A page reload or application restart does not lose unstarted Meetings or dispatch them again. The queue can resume safely after an interrupted run without duplicating Jobs.
- [ ] Existing single-Meeting processing and reprocessing remain available. Queue processing uses the same Preset health checks and Job progress/status reporting as individual processing.
- [ ] Backend and frontend tests cover queue creation, ordering, dispatch, duplicate-start protection, failure continuation, and recovery after restart.
