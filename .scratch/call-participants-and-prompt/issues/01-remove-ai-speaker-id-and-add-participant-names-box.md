# 01 - Call Participants, Domain Terms Profiles and ASR Prompting

**What to build:**
Redesign the pre-transcription configuration to provide two dedicated, high-leverage fields on the upload screen — **Call Participants** and **Domain Terms** — along with reusable **Vocabulary Profiles** (e.g., Tech/Dev, Legal, Financial) that prime speech recognition models without relying on external LLMs:

1. **Two Clean Fields in the Upload Modal (`frontend/src/pages/HomePage.tsx`)**:
   - **Participants Field (Meeting Attendees)**:
     - Multi-line textarea: *"Meeting Participants / Attendees"*.
     - Description: *"Paste names copied from Google Meet, Zoom, Teams, or call chat (one per line or separated by commas)"*.
     - Automatic cleaner: strips emails, timestamps, and status markers (e.g., `Alice Silva (Organizer)` -> `Alice Silva`).
     - Stored as structured `participants` in meeting metadata.
   - **Domain Terms Field (Jargon, Acronyms, Keywords)**:
     - Textarea: *"Domain Terms & Jargon"*.
     - Description: *"Technical terms, acronyms, product names, or project keywords"*.
     - Quick Profile Selector: a dropdown / chips bar allowing 1-click loading of a saved **Vocabulary Profile** into the terms field.
   - **Cleanup**:
     - Remove the old `KnownSpeakersInput` chip component.
     - Remove the old redundant "Additional vocabulary" field hidden inside Advanced Settings.

2. **Vocabulary Profiles (Glossary Templates)**:
   - Allow users to create and manage reusable term presets (e.g., "Engineering / Dev", "Finance & Operations", "Legal / Contracts").
   - Storage in `preferences.json` (backend: `preferences.py` and `/api/preferences`):
     ```json
     "vocabulary_profiles": [
       { "id": "dev", "name": "Dev / Engineering", "terms": "Docker, Kubernetes, gRPC, Celery, Redis, PyTorch, PR" },
       { "id": "business", "name": "Business / Sales", "terms": "CAC, LTV, churn, pipeline, EBITDA, B2B, outbound" }
     ]
     ```
   - Endpoints in `api/preferences.py` to list, save, and delete vocabulary profiles.
   - UI support: a "Save current terms as profile" action and management in `SettingsDialog.tsx`.

3. **ASR Model Prompting Integration**:
   - Merge `participants` and `terms` into the effective model vocabulary / prompt across all engines:
     - `whisper.cpp` / `faster-whisper`: passed via `--prompt` / `initial_prompt`:
       `"Participantes: Alice, Bob, Carlos. Termos: Kubernetes, Docker, deploy..."`
     - `qwen3-asr`: passed via `--context`.
     - `vibevoice`: passed via `context_info`.
   - Ensures zero phonetic corruption of attendee names or technical acronyms.

4. **1-Click Speaker Assignment in Meeting View (`frontend/src/components/SpeakerPanel.tsx` / `TranscriptView.tsx`)**:
   - In the transcript view, clicking or renaming an unidentified speaker ("Participant 1", "Participant 2") reveals a quick-select chip list with the meeting's participant names.
   - 1-click assigns the speaker to the chosen attendee name across all segments.

5. **Voice Profiles Preserved**:
   - Existing local voice profile biometrics (`VoiceProfile` / `SpeakerIdService`) remain 100% active for automatic recognition of enrolled voices.
   - No external LLM is invoked to guess speaker names.

**Blocked by:** 
- `.scratch/dual-track-audio/issues/01-dual-track-mic-and-system-diarization.md` (active execution).

**Status:** ready-for-agent

- [ ] Add `vocabulary_profiles` CRUD support in `preferences.py` and `api/preferences.py`.
- [ ] Replace old vocabulary/speaker inputs in `HomePage.tsx` with two dedicated fields: Participants and Domain Terms.
- [ ] Add Vocabulary Profile selector dropdown and "Save as profile" button in `HomePage.tsx`.
- [ ] Implement robust name extraction and cleaning parser in `frontend/src/utils/vocabulary.ts`.
- [ ] Pass structured `participants` and `vocabulary` to `POST /api/meetings` and store in `Meeting`.
- [ ] Verify prompt compilation and passing across all ASR engines (Whisper, Qwen3-ASR, VibeVoice).
- [ ] Add quick-select attendee chips in `SpeakerPanel.tsx` for 1-click speaker renaming.
- [ ] Add tests for vocabulary profile management, prompt combination, and participant cleaning.
