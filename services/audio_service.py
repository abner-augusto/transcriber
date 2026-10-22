import json
import math
import os
import re
import subprocess
from pathlib import Path

import numpy as np

from config import get_meeting_path
from services.track_analysis import SILENT, SPEECH, assign_roles, classify, speech_candidates

LOUDNORM = "loudnorm=I=-16:TP=-1.5:LRA=11"
# Track analysis: candidates examined per file, sampling windows, and the peak (dBFS) above
# which a track the windows found silent is not silent after all.
MAX_CANDIDATES = 8
SAMPLE_WINDOW_SECONDS = 60
SAMPLE_RATE = 8000
QUIET_PEAK_DB = -50.0
DUAL_MIC_OUTPUT = "mic_processed.wav"
DUAL_SYSTEM_OUTPUT = "system_processed.wav"
# The mix is written here and moved over audio.wav when ffmpeg is done, so that stopping a
# Reprocessing never cuts in half the audio of a Meeting that was already COMPLETED.
MIX_PART_OUTPUT = "audio.part.wav"


def _stderr_text(stderr) -> str:
    """Return subprocess stderr as readable text for error reporting."""
    if isinstance(stderr, bytes):
        return stderr.decode(errors="replace").strip()
    return str(stderr or "").strip()


def _run_ffprobe(cmd: list[str]):
    """ffprobe's JSON output, decoded as the UTF-8 it is (not the Windows code page)."""
    return subprocess.run(
        cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
        check=True, timeout=60,
    )


class AudioService:
    def extract_audio(self, input_path: str, meeting_id: str, track: dict | None = None) -> str:
        """Extract audio from input file as 16kHz mono WAV.

        ``track`` picks one candidate track of the file (see ``analyze_tracks``); without
        it ffmpeg's default audio stream is mixed down.
        """
        output_dir = get_meeting_path(meeting_id)
        output_path = str(output_dir / "audio.wav")

        # If input is already our output, skip extraction
        if Path(input_path).resolve() == Path(output_path).resolve():
            return output_path

        self._run_ffmpeg(self._track_command(input_path, output_path, track), timeout=600)  # 10 min
        return output_path

    @staticmethod
    def _track_command(input_path: str, output_path: str, track: dict | None) -> list[str]:
        """ffmpeg command making one candidate track a 16 kHz mono loudnorm WAV.

        A track is ``{"stream", "channel"}``: the ordinal of an audio stream (``-map
        0:a:N``, which a video stream does not shift) and, when the file's only stream is
        multi-channel, one of its channels (``None`` mixes the stream down).
        """
        mapping, filters = [], []
        if track is not None:
            mapping = ["-map", f"0:a:{track['stream']}"]
            if track.get("channel") is not None:
                filters.append(f"pan=mono|c0=c{track['channel']}")
        filters.append(LOUDNORM)
        return [
            "ffmpeg", "-y",
            "-i", input_path,
            "-vn",
            *mapping,
            "-af", ",".join(filters),
            "-acodec", "pcm_s16le",
            "-ar", "16000",
            "-ac", "1",
            output_path,
        ]

    @staticmethod
    def _run_ffmpeg(cmd: list[str], timeout: int, text: bool = True):
        """Run FFmpeg and retain its diagnostic stderr when it fails."""
        try:
            return subprocess.run(
                cmd,
                capture_output=True,
                text=text,
                # ffmpeg and ffprobe print UTF-8 whatever the Windows code page is: track
                # titles and file names carry accents.
                encoding="utf-8" if text else None,
                errors="replace" if text else None,
                check=True,
                timeout=timeout,
            )
        except subprocess.CalledProcessError as exc:
            stderr = _stderr_text(exc.stderr) or "(no stderr output)"
            raise RuntimeError(
                f"ffmpeg failed with exit code {exc.returncode}: {stderr}"
            ) from exc
        except subprocess.TimeoutExpired as exc:
            stderr = _stderr_text(exc.stderr) or "(no stderr output)"
            raise RuntimeError(
                f"ffmpeg timed out after {timeout}s: {stderr}"
            ) from exc

    def probe_audio(self, filepath: str) -> dict:
        """Probe a file's audio layout via ffprobe.

        Returns {"stream_count": int, "channels": int, "streams": [{"stream", "channels", "title"}]}
        where stream_count is the number of audio streams and channels is the channel
        count of the first audio stream. ``stream`` is the ordinal among the audio streams
        (what ``-map 0:a:N`` counts, so a video stream does not shift it) and ``title`` is
        the name the recorder gave the track, or None.
        """
        cmd = [
            "ffprobe",
            "-v", "quiet",
            "-print_format", "json",
            "-show_streams",
            filepath,
        ]
        result = _run_ffprobe(cmd)
        info = json.loads(result.stdout)
        audio_streams = []
        for stream in info.get("streams", []):
            if stream.get("codec_type") == "audio" and stream.get("channels"):
                audio_streams.append({
                    "stream": len(audio_streams),
                    "channels": int(stream["channels"]),
                    "title": (stream.get("tags") or {}).get("title"),
                })
        channels = audio_streams[0]["channels"] if audio_streams else 1
        return {
            "stream_count": len(audio_streams),
            "channels": channels,
            "streams": audio_streams,
        }

    def analyze_tracks(self, filepath: str) -> dict:
        """Find the tracks of one file and decide which is the mic and which the system.

        A candidate track is a stream of the file or, when the file has a single
        multi-channel stream, one of its channels. Each is sampled and classified
        (``services.track_analysis``): silent, a copy of another, the mix of the others,
        or speech. Among the speech tracks the names the recorder gave decide which is the
        mic and which the system; without clear names the first two, in file order.

        Returns ``{"tracks": [...], "mic", "system", "audio", "manual": False}``. ``mic``
        and ``system`` are set when there are two or more speech tracks. With exactly one,
        ``audio`` names it and the file is read as a single track. ``manual`` becomes True
        when the user overrules the choice.
        """
        probe = self.probe_audio(filepath)
        candidates = self._candidates(probe)
        duration = self.get_duration(filepath)

        samples = [self._sample(filepath, c, duration) for c in candidates]
        statuses = classify(samples)
        for i, status in enumerate(statuses):
            # The windows may have missed a short burst: a track is silent only if no part of
            # the whole file rises above the floor.
            if status == SILENT and self._peak_db(filepath, candidates[i]) > QUIET_PEAK_DB:
                statuses[i] = SPEECH

        def selector(candidate: dict) -> dict:
            return {"stream": candidate["stream"], "channel": candidate["channel"]}

        used = speech_candidates(statuses)
        layout = {"mic": None, "system": None, "audio": None, "manual": False}
        roles = assign_roles([c["title"] for c in candidates], used)
        if roles:
            layout["mic"] = selector(candidates[roles[0]])
            layout["system"] = selector(candidates[roles[1]])
        elif len(used) == 1:
            layout["audio"] = selector(candidates[used[0]])
        layout["tracks"] = [
            {
                **selector(c),
                "title": c["title"],
                "status": status,
                "level_db": self._level_db(sample),
            }
            for c, status, sample in zip(candidates, statuses, samples)
        ]
        return layout

    @staticmethod
    def _candidates(probe: dict) -> list[dict]:
        streams = probe["streams"]
        if len(streams) == 1 and streams[0]["channels"] >= 2:
            only = streams[0]
            return [
                {"stream": 0, "channel": channel, "title": only["title"]}
                for channel in range(min(only["channels"], MAX_CANDIDATES))
            ]
        # A stereo stream next to others is one track: its channels are not told apart.
        return [
            {"stream": s["stream"], "channel": None, "title": s["title"]}
            for s in streams[:MAX_CANDIDATES]
        ]

    @staticmethod
    def _level_db(sample) -> float:
        rms = float(np.sqrt(np.mean(np.square(sample, dtype=np.float64)))) if len(sample) else 0.0
        return round(20 * math.log10(rms), 1) if rms > 0 else -120.0

    def _sample(self, filepath: str, candidate: dict, duration: float) -> "np.ndarray":
        """A few short windows of one candidate track, 8 kHz mono: enough to compare tracks
        without decoding the whole recording."""
        if duration <= 3 * SAMPLE_WINDOW_SECONDS:
            windows = [(0.0, duration)]
        else:
            windows = [
                (max(0.0, fraction * duration - SAMPLE_WINDOW_SECONDS / 2), SAMPLE_WINDOW_SECONDS)
                for fraction in (0.1, 0.5, 0.9)
            ]
        parts = []
        for start, length in windows:
            cmd = [
                "ffmpeg", "-v", "error",
                "-ss", f"{start:.3f}", "-t", f"{length:.3f}",
                "-i", filepath,
                *self._select(candidate),
                "-ac", "1", "-ar", str(SAMPLE_RATE),
                "-f", "f32le", "-",
            ]
            result = self._run_ffmpeg(cmd, timeout=300, text=False)
            parts.append(np.frombuffer(result.stdout, dtype=np.float32))
        return np.concatenate(parts)

    def _peak_db(self, filepath: str, candidate: dict) -> float:
        """Loudest sample of the whole track in dBFS."""
        cmd = [
            "ffmpeg", "-v", "info", "-i", filepath,
            *self._select(candidate, extra_filters=["volumedetect"]),
            "-vn", "-f", "null", "-",
        ]
        result = self._run_ffmpeg(cmd, timeout=600)
        match = re.search(r"max_volume:\s*(-?[\d.]+|-inf) dB", result.stderr or "")
        return float(match.group(1)) if match else -120.0

    @staticmethod
    def _select(candidate: dict, extra_filters: list[str] | None = None) -> list[str]:
        """ffmpeg arguments reading one candidate track as mono."""
        filters = []
        if candidate.get("channel") is not None:
            filters.append(f"pan=mono|c0=c{candidate['channel']}")
        filters += extra_filters or []
        return [
            "-map", f"0:a:{candidate['stream']}",
            *(["-af", ",".join(filters)] if filters else []),
        ]

    def extract_dual_audio(
        self, mic_path: str, system_path: str, meeting_id: str, layout: dict | None = None
    ) -> str:
        """Produce the three dual-track artifacts: processed mic, processed system, audio.

        - mic_processed.wav: 16kHz mono, loudnorm, from the mic source.
        - system_processed.wav: 16kHz mono, loudnorm, from the system source.
        - audio.wav: a balanced 16kHz mono mix of both, for the frontend player and
          unified ASR transcription.

        When mic_path and system_path resolve to the same file, the file is split into
        the two tracks ``layout`` names. Processed outputs deliberately use
        different names from uploaded source files so legacy rows pointing at
        ``mic.wav``/``system.wav`` cannot trigger an in-place FFmpeg conversion.
        """
        mic_out, system_out = self.extract_dual_tracks(mic_path, system_path, meeting_id, layout)
        directory = get_meeting_path(meeting_id)
        mixed_out = directory / "audio.wav"
        part = directory / MIX_PART_OUTPUT
        try:
            self._mix(mic_out, system_out, str(part))
            os.replace(part, mixed_out)
        finally:
            part.unlink(missing_ok=True)
        return str(mixed_out)

    def extract_dual_tracks(
        self, mic_path: str, system_path: str, meeting_id: str, layout: dict | None = None
    ) -> tuple[str, str]:
        """Produce only ``mic_processed.wav`` and ``system_processed.wav`` (their paths).

        What a dual-track Re-diarize reads when the app no longer holds them. The inputs
        are only read: the outputs go into the Meeting's folder.
        """
        output_dir = get_meeting_path(meeting_id)
        mic_out = str(output_dir / DUAL_MIC_OUTPUT)
        system_out = str(output_dir / DUAL_SYSTEM_OUTPUT)

        if Path(mic_path).resolve() == Path(system_path).resolve():
            self._split_dual(mic_path, mic_out, system_out, layout)
        else:
            self._extract_mono(mic_path, mic_out)
            self._extract_mono(system_path, system_out)
        return mic_out, system_out

    def _extract_mono(self, input_path: str, output_path: str) -> None:
        """Extract a single source file as 16kHz mono WAV with loudnorm."""
        self._run_ffmpeg(self._track_command(input_path, output_path, None), timeout=600)

    def _split_dual(self, input_path: str, mic_out: str, system_out: str, layout: dict | None) -> None:
        """Split a single dual-track file into mic and system mono tracks.

        ``layout`` says which candidate track is which (``analyze_tracks``). Without one
        (a Meeting made before layouts existed) the file's first two tracks are used: the
        first two streams, or the two channels of a single stereo stream.
        """
        layout = layout or self._first_two_tracks(self.probe_audio(input_path))
        self._run_ffmpeg(self._track_command(input_path, mic_out, layout["mic"]), timeout=600)
        self._run_ffmpeg(self._track_command(input_path, system_out, layout["system"]), timeout=600)

    @staticmethod
    def _first_two_tracks(probe: dict) -> dict:
        if probe["stream_count"] >= 2:
            return {
                "mic": {"stream": 0, "channel": None},
                "system": {"stream": 1, "channel": None},
            }
        return {
            "mic": {"stream": 0, "channel": 0},
            "system": {"stream": 0, "channel": 1},
        }

    def _mix(self, mic_path: str, system_path: str, output_path: str) -> None:
        """Mix the two mono tracks into a balanced 16kHz mono WAV.

        amix with normalize=1 balances the two inputs so neither dominates and the
        output does not clip.
        """
        cmd = [
            "ffmpeg", "-y",
            "-i", mic_path,
            "-i", system_path,
            "-filter_complex", "[0:a][1:a]amix=inputs=2:normalize=1",
            "-acodec", "pcm_s16le",
            "-ar", "16000",
            "-ac", "1",
            output_path,
        ]
        self._run_ffmpeg(cmd, timeout=600)

    def get_duration(self, filepath: str) -> float:
        """Get audio/video duration in seconds via ffprobe."""
        cmd = [
            "ffprobe",
            "-v", "quiet",
            "-print_format", "json",
            "-show_format",
            filepath,
        ]
        result = _run_ffprobe(cmd)
        info = json.loads(result.stdout)
        return float(info["format"]["duration"])

    def extract_segment(self, audio_path: str, start: float, end: float, output_path: str) -> str:
        """Extract a segment of audio."""
        cmd = [
            "ffmpeg", "-y",
            "-i", audio_path,
            "-ss", str(start),
            "-to", str(end),
            "-acodec", "pcm_s16le",
            "-ar", "16000",
            "-ac", "1",
            output_path,
        ]
        self._run_ffmpeg(cmd, timeout=300)  # 5 min
        return output_path
