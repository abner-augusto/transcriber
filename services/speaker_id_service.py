import logging
from pathlib import Path

import numpy as np
import soundfile as sf

from engines import Turn

log = logging.getLogger(__name__)

# Speaker colors palette
SPEAKER_COLORS = [
    "#6366f1",  # indigo
    "#ec4899",  # pink
    "#10b981",  # emerald
    "#f59e0b",  # amber
    "#3b82f6",  # blue
    "#ef4444",  # red
    "#8b5cf6",  # violet
    "#14b8a6",  # teal
    "#f97316",  # orange
    "#06b6d4",  # cyan
]

PROFILE_MATCH_THRESHOLD = 0.55
MIN_PROFILE_SAMPLE_SECONDS = 2.0
MAX_PROFILE_SAMPLE_SECONDS = 15


class SpeakerIdService:
    """Names the Speakers found in a Meeting.

    Every Speaker starts as "Participant N". A saved Voice Profile whose embedding
    matches a Speaker's voice then overrides that name.
    """

    def name_speakers(
        self,
        db,
        speaker_labels: list[str],
        turns: list[Turn],
        audio_path: str,
    ) -> dict[str, dict]:
        """Return {speaker_label: {name, confidence, identified_by}} for every label."""
        speaker_info = self._participant_names(speaker_labels)

        profiles = self._load_profiles(db)
        if profiles and audio_path:
            self._apply_voice_profiles(speaker_info, profiles, turns, audio_path)

        return speaker_info

    def _participant_names(self, speaker_labels: list[str]) -> dict[str, dict]:
        return {
            label: {"name": f"Participant {i + 1}", "confidence": None, "identified_by": None}
            for i, label in enumerate(sorted(set(speaker_labels)))
        }

    def _load_profiles(self, db) -> list:
        from preferences import load_preferences

        if not load_preferences().get("speaker_profiles_enabled", True):
            return []

        from models.speaker_profile import SpeakerProfile

        return db.query(SpeakerProfile).all()

    def _apply_voice_profiles(
        self,
        speaker_info: dict[str, dict],
        profiles: list,
        turns: list[Turn],
        audio_path: str,
    ) -> None:
        from services.embedding_service import EmbeddingService

        embedding_service = EmbeddingService()

        for label, info in speaker_info.items():
            sample_turns = self._best_turns_for_speaker(turns, label)
            if not sample_turns:
                continue

            try:
                embedding = self._embed_speaker_turns(
                    embedding_service, audio_path, label, sample_turns
                )
            except Exception as e:
                log.debug(f"Profile matching failed for {label}: {e}")
                continue

            best_profile = None
            best_sim = 0.0
            for profile in profiles:
                sim = embedding_service.cosine_similarity(embedding, profile.get_embedding())
                if sim > best_sim:
                    best_sim = sim
                    best_profile = profile

            if best_profile and best_sim >= PROFILE_MATCH_THRESHOLD:
                info["name"] = best_profile.name
                info["identified_by"] = "voice_profile"
                info["confidence"] = round(best_sim, 3)

    def _best_turns_for_speaker(
        self,
        turns: list[Turn],
        label: str,
        max_total_seconds: float = MAX_PROFILE_SAMPLE_SECONDS,
    ) -> list[Turn]:
        """Select best (longest) turns for a speaker up to max_total_seconds."""
        mine = [
            t
            for t in turns
            if t.speaker == label and (t.end - t.start) >= MIN_PROFILE_SAMPLE_SECONDS
        ]
        if not mine:
            # Fallback to shorter turns if no single turn >= 2s
            mine = [
                t for t in turns if t.speaker == label and (t.end - t.start) >= 1.0
            ]
            if not mine:
                return []

        mine.sort(key=lambda t: t.end - t.start, reverse=True)
        selected = []
        total = 0.0
        for t in mine:
            selected.append(t)
            total += t.end - t.start
            if total >= max_total_seconds:
                break
        return selected

    def _longest_turn(self, turns: list[Turn], label: str) -> Turn | None:
        """Longest Turn by this Speaker — kept for backward compatibility."""
        turns_list = self._best_turns_for_speaker(turns, label)
        return turns_list[0] if turns_list else None

    def _embed_speaker_turns(
        self, embedding_service, audio_path: str, label: str, turns: list[Turn]
    ) -> np.ndarray:
        """Extract speaker embedding from concatenated audio slices of the speaker's turns."""
        temp_wav = str(Path(audio_path).parent / f"profile_match_{label}.wav")
        try:
            data, sr = sf.read(audio_path, dtype="float32", always_2d=True)
            waveform = data[:, 0]
            slices = []
            total_samples = 0
            max_samples = int(MAX_PROFILE_SAMPLE_SECONDS * sr)

            for turn in turns:
                start_sample = max(0, int(turn.start * sr))
                end_sample = min(len(waveform), int(turn.end * sr))
                if end_sample > start_sample:
                    slice_data = waveform[start_sample:end_sample]
                    slices.append(slice_data)
                    total_samples += len(slice_data)
                    if total_samples >= max_samples:
                        break

            if not slices:
                raise ValueError(f"No audio samples found for speaker {label}")

            combined = np.concatenate(slices)[:max_samples]
            sf.write(temp_wav, combined, sr)
            return embedding_service.extract_embedding(temp_wav)
        finally:
            Path(temp_wav).unlink(missing_ok=True)

    def get_color(self, index: int) -> str:
        """Return a color from the palette, cycling if index exceeds palette size."""
        return SPEAKER_COLORS[index % len(SPEAKER_COLORS)]
