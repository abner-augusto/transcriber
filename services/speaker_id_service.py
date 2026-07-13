import logging
import subprocess
from pathlib import Path

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
            sample = self._longest_turn(turns, label)
            if not sample:
                continue

            try:
                embedding = self._embed_segment(embedding_service, audio_path, label, sample)
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

    def _longest_turn(self, turns: list[Turn], label: str) -> Turn | None:
        """Longest Turn by this Speaker — the best sample to embed. None if too short."""
        mine = [t for t in turns if t.speaker == label]
        if not mine:
            return None
        longest = max(mine, key=lambda t: t.end - t.start)
        if longest.end - longest.start < MIN_PROFILE_SAMPLE_SECONDS:
            return None
        return longest

    def _embed_segment(self, embedding_service, audio_path: str, label: str, turn: Turn):
        temp_wav = str(Path(audio_path).parent / f"profile_match_{label}.wav")
        duration = min(turn.end - turn.start, MAX_PROFILE_SAMPLE_SECONDS)
        subprocess.run(
            [
                "ffmpeg", "-y",
                "-ss", str(turn.start),
                "-t", str(duration),
                "-i", audio_path,
                "-ar", "16000", "-ac", "1",
                temp_wav,
            ],
            capture_output=True,
            timeout=15,
        )
        try:
            return embedding_service.extract_embedding(temp_wav)
        finally:
            Path(temp_wav).unlink(missing_ok=True)

    def get_color(self, index: int) -> str:
        """Return a color from the palette, cycling if index exceeds palette size."""
        return SPEAKER_COLORS[index % len(SPEAKER_COLORS)]
