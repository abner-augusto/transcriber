import json
import subprocess
from pathlib import Path

from config import get_meeting_path

LOUDNORM = "loudnorm=I=-16:TP=-1.5:LRA=11"
DUAL_MIC_OUTPUT = "mic_processed.wav"
DUAL_SYSTEM_OUTPUT = "system_processed.wav"


def _stderr_text(stderr) -> str:
    """Return subprocess stderr as readable text for error reporting."""
    if isinstance(stderr, bytes):
        return stderr.decode(errors="replace").strip()
    return str(stderr or "").strip()


class AudioService:
    def extract_audio(self, input_path: str, meeting_id: str) -> str:
        """Extract audio from input file as 16kHz mono WAV."""
        output_dir = get_meeting_path(meeting_id)
        output_path = str(output_dir / "audio.wav")

        # If input is already our output, skip extraction
        if Path(input_path).resolve() == Path(output_path).resolve():
            return output_path

        cmd = [
            "ffmpeg", "-y",
            "-i", input_path,
            "-vn",
            "-af", LOUDNORM,
            "-acodec", "pcm_s16le",
            "-ar", "16000",
            "-ac", "1",
            output_path,
        ]
        self._run_ffmpeg(cmd, timeout=600)  # 10 min
        return output_path

    @staticmethod
    def _run_ffmpeg(cmd: list[str], timeout: int):
        """Run FFmpeg and retain its diagnostic stderr when it fails."""
        try:
            return subprocess.run(
                cmd,
                capture_output=True,
                text=True,
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

        Returns {"stream_count": int, "channels": int, "streams": [{"index", "channels"}]}
        where stream_count is the number of audio streams and channels is the channel
        count of the first audio stream. Used to detect stereo (channels >= 2) and
        multi-stream (stream_count >= 2) containers from OBS.
        """
        cmd = [
            "ffprobe",
            "-v", "quiet",
            "-print_format", "json",
            "-show_streams",
            filepath,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=60)
        info = json.loads(result.stdout)
        audio_streams = []
        for stream in info.get("streams", []):
            if stream.get("codec") and stream.get("channels"):
                audio_streams.append({
                    "index": stream.get("index"),
                    "channels": int(stream["channels"]),
                })
        channels = audio_streams[0]["channels"] if audio_streams else 1
        return {
            "stream_count": len(audio_streams),
            "channels": channels,
            "streams": audio_streams,
        }

    def extract_dual_audio(self, mic_path: str, system_path: str, meeting_id: str) -> str:
        """Produce the three dual-track artifacts: processed mic, processed system, audio.

        - mic_processed.wav: 16kHz mono, loudnorm, from the mic source.
        - system_processed.wav: 16kHz mono, loudnorm, from the system source.
        - audio.wav: a balanced 16kHz mono mix of both, for the frontend player and
          unified ASR transcription.

        When mic_path and system_path resolve to the same file, the file is split:
        channel 0 -> mic, channel 1 -> system. Processed outputs deliberately use
        different names from uploaded source files so legacy rows pointing at
        ``mic.wav``/``system.wav`` cannot trigger an in-place FFmpeg conversion.
        """
        output_dir = get_meeting_path(meeting_id)
        mic_out = str(output_dir / DUAL_MIC_OUTPUT)
        system_out = str(output_dir / DUAL_SYSTEM_OUTPUT)
        mixed_out = str(output_dir / "audio.wav")

        same_file = Path(mic_path).resolve() == Path(system_path).resolve()

        if same_file:
            self._split_dual(mic_path, mic_out, system_out)
        else:
            self._extract_mono(mic_path, mic_out)
            self._extract_mono(system_path, system_out)

        self._mix(mic_out, system_out, mixed_out)
        return mixed_out

    def _extract_mono(self, input_path: str, output_path: str) -> None:
        """Extract a single source file as 16kHz mono WAV with loudnorm."""
        cmd = [
            "ffmpeg", "-y",
            "-i", input_path,
            "-vn",
            "-af", LOUDNORM,
            "-acodec", "pcm_s16le",
            "-ar", "16000",
            "-ac", "1",
            output_path,
        ]
        self._run_ffmpeg(cmd, timeout=600)

    def _split_dual(self, input_path: str, mic_out: str, system_out: str) -> None:
        """Split a single dual-track file into mic and system mono tracks.

        Two layouts are handled:
        - Stereo (1 stream, >= 2 channels): channel 0 -> mic, channel 1 -> system,
          extracted with the pan filter.
        - Multi-stream (>= 2 mono streams, e.g. OBS): stream 0 -> mic, stream 1 -> system,
          extracted with -map.
        """
        probe = self.probe_audio(input_path)

        if probe["stream_count"] >= 2:
            # Multi-stream: map each mono stream.
            cmd_mic = [
                "ffmpeg", "-y",
                "-i", input_path,
                "-map", "0:a:0",
                "-af", LOUDNORM,
                "-acodec", "pcm_s16le",
                "-ar", "16000",
                "-ac", "1",
                mic_out,
            ]
            cmd_system = [
                "ffmpeg", "-y",
                "-i", input_path,
                "-map", "0:a:1",
                "-af", LOUDNORM,
                "-acodec", "pcm_s16le",
                "-ar", "16000",
                "-ac", "1",
                system_out,
            ]
        else:
            # Stereo: extract channel 0 and channel 1 via the pan filter.
            cmd_mic = [
                "ffmpeg", "-y",
                "-i", input_path,
                "-af", f"pan=mono|c0=1:c1=0,{LOUDNORM}",
                "-acodec", "pcm_s16le",
                "-ar", "16000",
                "-ac", "1",
                mic_out,
            ]
            cmd_system = [
                "ffmpeg", "-y",
                "-i", input_path,
                "-af", f"pan=mono|c0=0:c1=1,{LOUDNORM}",
                "-acodec", "pcm_s16le",
                "-ar", "16000",
                "-ac", "1",
                system_out,
            ]

        self._run_ffmpeg(cmd_mic, timeout=600)
        self._run_ffmpeg(cmd_system, timeout=600)

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
        result = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=60)
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
