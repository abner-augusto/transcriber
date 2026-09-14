"""The adapters, tested at the only place they can go wrong without a GPU: parsing.

The fixtures are real output — captured from whisper-cli and parakeet-cli running on
30 seconds of test.mp3 — so these tests fail if either tool changes its format.
"""

import json
import logging
import sys
import types
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from engines import Diarizer, Transcriber, Turn, Word, make_transcriber
from engines.chunking import chunk_bounds
from engines.parakeet_cpp import MIN_TAIL_SECONDS as PARAKEET_MIN_TAIL_SECONDS
from engines.parakeet_cpp import ParakeetCppTranscriber
from engines.parakeet_cpp import parse_words as parse_parakeet
from engines.whisper_cpp import MIN_TAIL_SECONDS as WHISPER_MIN_TAIL_SECONDS
from engines.whisper_cpp import WhisperCppTranscriber
from engines.whisper_cpp import parse_words as parse_whisper

from .fakes import FakeDiarizer, FakeTranscriber

FIXTURES = Path(__file__).parent / "fixtures"
SAMPLE_RATE = 16000


def test_a_fake_satisfies_the_ports():
    """If this fails, the fakes have drifted from the ports and every test above is a lie."""
    assert isinstance(FakeTranscriber([]), Transcriber)
    assert isinstance(FakeDiarizer([]), Diarizer)


def test_whisper_subword_tokens_are_stitched_back_into_words():
    """whisper.cpp splits "Rádio" into " R" + "ád" + "io". A Word is the whole thing."""
    data = json.loads((FIXTURES / "whisper_full.json").read_text(encoding="utf-8"))

    words = parse_whisper(data)

    assert [w.text for w in words] == [
        " no", " ar", " pela", " Rádio", " Universitária", " FM,", " Sem", " Fronteiras,", " Plural",
    ]
    assert "".join(w.text for w in words).strip() == (
        "no ar pela Rádio Universitária FM, Sem Fronteiras, Plural"
    )


def test_whisper_control_tokens_never_reach_the_transcript():
    data = json.loads((FIXTURES / "whisper_full.json").read_text(encoding="utf-8"))

    words = parse_whisper(data)

    assert not any("[_" in w.text for w in words)
    assert all(w.end >= w.start for w in words)
    assert all(0.0 <= w.confidence <= 1.0 for w in words)


def test_parakeet_words_are_read_past_the_cuda_chatter():
    """parakeet-cli prints its JSON after the backend has finished talking to itself."""
    stdout = (FIXTURES / "parakeet_stdout.txt").read_text(encoding="utf-8")

    words = parse_parakeet(stdout)

    assert words[0] == Word(start=3.2, end=3.52, text=" No", confidence=0.9925)
    assert "".join(w.text for w in words).strip() == "No ar, pela Rádio Universitária FM."


def test_parakeet_without_json_is_an_error_not_an_empty_transcript():
    with pytest.raises(RuntimeError):
        parse_parakeet("ggml_cuda_init: found 1 CUDA devices\n")


def test_both_engines_agree_on_the_shape_of_a_word():
    """The port's whole promise: two Engines, one currency."""
    whisper = parse_whisper(json.loads((FIXTURES / "whisper_full.json").read_text(encoding="utf-8")))
    parakeet = parse_parakeet((FIXTURES / "parakeet_stdout.txt").read_text(encoding="utf-8"))

    for word in whisper + parakeet:
        assert isinstance(word, Word)
        assert word.text.startswith(" ")  # join-ready, per the Word contract
        assert word.end >= word.start


def test_chunk_bounds_cuts_long_audio_in_a_pause_rather_than_through_a_word():
    """A single compute graph or a single subprocess call cannot swallow a whole meeting."""
    audio = np.full(700 * SAMPLE_RATE, 0.5, dtype=np.float32)
    audio[295 * SAMPLE_RATE : 296 * SAMPLE_RATE] = 0.0  # a pause, just shy of the boundary

    cuts = chunk_bounds(audio, SAMPLE_RATE, chunk_seconds=300, min_tail_seconds=10)

    assert 295 <= cuts[0][1] <= 296  # cut in the pause, not at the nominal 300s
    assert cuts[0][0] == 0.0
    assert cuts[-1][1] == pytest.approx(700.0)
    assert all(before[1] == after[0] for before, after in zip(cuts, cuts[1:]))  # no audio lost


def test_chunk_bounds_gives_a_sliver_of_a_tail_to_the_chunk_before_it():
    """Trailing silence is the quietest thing in a file, so a cut snaps hard against it."""
    audio = np.full(610 * SAMPLE_RATE, 0.5, dtype=np.float32)
    audio[600 * SAMPLE_RATE :] = 0.0

    cuts = chunk_bounds(audio, SAMPLE_RATE, chunk_seconds=300, min_tail_seconds=10)

    assert all(end - start >= 10 for start, end in cuts)
    assert cuts[-1][1] == pytest.approx(610.0)


def test_parakeet_puts_every_chunks_words_back_on_the_meetings_timeline(tmp_path, monkeypatch):
    """A chunk's Words are timed from the chunk's own zero. The meeting's are not."""
    audio = np.full(700 * SAMPLE_RATE, 0.5, dtype=np.float32)
    audio_path = tmp_path / "audio.wav"
    sf.write(audio_path, audio, SAMPLE_RATE)
    monkeypatch.setattr(
        ParakeetCppTranscriber,
        "_transcribe_file",
        lambda self, path: [Word(start=1.0, end=1.5, text=" olá", confidence=0.9)],
    )

    words = ParakeetCppTranscriber(cli_path="x", model_path="m.gguf").transcribe(str(audio_path))

    chunk_starts = [start for start, _ in chunk_bounds(audio, SAMPLE_RATE, 300, PARAKEET_MIN_TAIL_SECONDS)]
    assert [w.start for w in words] == [pytest.approx(start + 1.0) for start in chunk_starts]
    assert [w.end for w in words] == [pytest.approx(start + 1.5) for start in chunk_starts]


def test_parakeet_leaves_audio_it_can_swallow_whole_alone(tmp_path, monkeypatch):
    """Short audio goes to parakeet-cli as it is — no chunk file, no copy."""
    audio_path = tmp_path / "audio.wav"
    sf.write(audio_path, np.full(60 * SAMPLE_RATE, 0.5, dtype=np.float32), SAMPLE_RATE)
    transcribed: list[str] = []
    monkeypatch.setattr(
        ParakeetCppTranscriber,
        "_transcribe_file",
        lambda self, path: transcribed.append(path) or [],
    )

    ParakeetCppTranscriber(cli_path="x", model_path="m.gguf").transcribe(str(audio_path))

    assert transcribed == [str(audio_path)]


def test_whisper_puts_every_chunks_words_back_on_the_meetings_timeline(tmp_path, monkeypatch):
    """Long audio is chunked for whisper.cpp too — a call over a full meeting can outrun
    TRANSCRIBE_TIMEOUT_SECONDS even though nothing here is VRAM-bound."""
    audio = np.full(2000 * SAMPLE_RATE, 0.5, dtype=np.float32)
    audio_path = tmp_path / "audio.wav"
    sf.write(audio_path, audio, SAMPLE_RATE)
    monkeypatch.setattr(
        WhisperCppTranscriber,
        "_transcribe_file",
        lambda self, path, vocabulary=None: [Word(start=1.0, end=1.5, text=" olá", confidence=0.9)],
    )

    words = WhisperCppTranscriber(cli_path="x", model_path="m.bin").transcribe(str(audio_path))

    chunk_starts = [start for start, _ in chunk_bounds(audio, SAMPLE_RATE, 900, WHISPER_MIN_TAIL_SECONDS)]
    assert len(chunk_starts) > 1  # the fixture is long enough to actually need chunking
    assert [w.start for w in words] == [pytest.approx(start + 1.0) for start in chunk_starts]
    assert [w.end for w in words] == [pytest.approx(start + 1.5) for start in chunk_starts]


def test_whisper_leaves_audio_it_can_swallow_whole_alone(tmp_path, monkeypatch):
    """Short audio goes to whisper-cli as it is — no chunk file, no copy."""
    audio_path = tmp_path / "audio.wav"
    sf.write(audio_path, np.full(60 * SAMPLE_RATE, 0.5, dtype=np.float32), SAMPLE_RATE)
    transcribed: list[str] = []
    monkeypatch.setattr(
        WhisperCppTranscriber,
        "_transcribe_file",
        lambda self, path, vocabulary=None: transcribed.append(path) or [],
    )

    WhisperCppTranscriber(cli_path="x", model_path="m.bin").transcribe(str(audio_path))

    assert transcribed == [str(audio_path)]


def test_a_preset_names_the_engine_it_runs_on():
    transcriber = make_transcriber({
        "id": "whisper-large-v3-turbo",
        "engine": "whisper.cpp",
        "model_path": "./models/ggml-large-v3-turbo.bin",
        "language": "pt",
    })

    assert isinstance(transcriber, Transcriber)
    assert transcriber.language == "pt"


def test_faster_whisper_preset_creation():
    transcriber = make_transcriber({
        "id": "faster-whisper-large-v3-turbo",
        "engine": "faster-whisper",
        "model_path": "large-v3-turbo",
        "language": "pt",
        "vad_filter": True,
    })

    assert isinstance(transcriber, Transcriber)
    assert transcriber.language == "pt"
    assert transcriber.model_path == "large-v3-turbo"


def test_faster_whisper_words_parsing():
    from engines.faster_whisper import parse_words_from_segments
    from types import SimpleNamespace

    mock_segments = [
        SimpleNamespace(
            words=[
                SimpleNamespace(start=0.0, end=0.4, word="Olá", probability=0.98),
                SimpleNamespace(start=0.4, end=0.5, word=",", probability=0.99),
                SimpleNamespace(start=0.5, end=1.0, word=" mundo", probability=0.95),
                SimpleNamespace(start=1.0, end=1.1, word="!", probability=0.99),
            ]
        )
    ]

    words = parse_words_from_segments(mock_segments)

    assert len(words) == 4
    assert words[0] == Word(start=0.0, end=0.4, text=" Olá", confidence=0.98)
    assert words[1] == Word(start=0.4, end=0.5, text=",", confidence=0.99)
    assert words[2] == Word(start=0.5, end=1.0, text=" mundo", confidence=0.95)
    assert words[3] == Word(start=1.0, end=1.1, text="!", confidence=0.99)
    assert "".join(w.text for w in words).strip() == "Olá, mundo!"


def test_an_unknown_engine_fails_loudly():
    with pytest.raises(ValueError, match="Unknown transcription engine"):
        make_transcriber({"id": "x", "engine": "deepgram", "model_path": "x"})


def test_whisper_dtw_preset_detection_from_model_name():
    from engines.whisper_cpp import detect_dtw_preset_from_model

    assert detect_dtw_preset_from_model("models/ggml-large-v3-turbo.bin") == "large.v3.turbo"
    assert detect_dtw_preset_from_model("models/ggml-large-v3.bin") == "large.v3"
    assert detect_dtw_preset_from_model("models/ggml-large-v2.bin") == "large.v2"
    assert detect_dtw_preset_from_model("models/ggml-large-v1.bin") == "large.v1"
    assert detect_dtw_preset_from_model("models/ggml-medium.bin") == "medium"
    assert detect_dtw_preset_from_model("models/ggml-medium.en.bin") == "medium.en"
    assert detect_dtw_preset_from_model("models/ggml-small.bin") == "small"
    assert detect_dtw_preset_from_model("models/ggml-small.en.bin") == "small.en"
    assert detect_dtw_preset_from_model("models/ggml-base.bin") == "base"
    assert detect_dtw_preset_from_model("models/ggml-tiny.bin") == "tiny"
    assert detect_dtw_preset_from_model("models/custom-unknown.bin") is None


def test_whisper_command_construction_with_dtw():
    transcriber = WhisperCppTranscriber(
        cli_path="whisper-cli",
        model_path="models/ggml-large-v3-turbo.bin",
        language="pt",
        dtw_enabled=True,
    )
    cmd = transcriber.build_command(
        audio_path="test.wav",
        vocabulary="Glossary terms",
        dtw_preset=transcriber.resolve_dtw_preset(),
    )
    assert cmd == [
        "whisper-cli",
        "-m", "models/ggml-large-v3-turbo.bin",
        "-f", "test.wav",
        "-l", "pt",
        "-ojf",
        "-of", "test.wav",
        "-dtw", "large.v3.turbo",
        "-nfa",
        "--prompt", "Glossary terms",
    ]


def test_whisper_command_construction_without_dtw():
    transcriber = WhisperCppTranscriber(
        cli_path="whisper-cli",
        model_path="models/ggml-large-v3-turbo.bin",
        language="pt",
        dtw_enabled=False,
    )
    cmd = transcriber.build_command(
        audio_path="test.wav",
        vocabulary="Glossary terms",
        dtw_preset=transcriber.resolve_dtw_preset(),
    )
    assert "-dtw" not in cmd
    assert "-nfa" not in cmd
    assert cmd == [
        "whisper-cli",
        "-m", "models/ggml-large-v3-turbo.bin",
        "-f", "test.wav",
        "-l", "pt",
        "-ojf",
        "-of", "test.wav",
        "--prompt", "Glossary terms",
    ]


def test_whisper_dtw_capability_detection(tmp_path, monkeypatch):
    import subprocess
    from engines.whisper_cpp import detect_whisper_dtw_capability

    fake_cli = tmp_path / "fake-whisper-cli.exe"
    fake_cli.write_text("binary", encoding="utf-8")

    # When --help outputs -dtw
    def mock_run_with_dtw(*args, **kwargs):
        class MockResult:
            stdout = "options:\n  -dtw MODEL --dtw MODEL compute token-level timestamps\n"
            stderr = ""
        return MockResult()

    monkeypatch.setattr(subprocess, "run", mock_run_with_dtw)
    assert detect_whisper_dtw_capability(str(fake_cli)) is True

    # When --help does NOT output -dtw
    def mock_run_without_dtw(*args, **kwargs):
        class MockResult:
            stdout = "options:\n  -m MODEL --model MODEL\n"
            stderr = ""
        return MockResult()

    monkeypatch.setattr(subprocess, "run", mock_run_without_dtw)
    assert detect_whisper_dtw_capability(str(fake_cli)) is False

    # When binary does not exist
    assert detect_whisper_dtw_capability(str(tmp_path / "nonexistent.exe")) is False


def test_whisper_dtw_fallback_handling_on_failure(tmp_path, monkeypatch):
    """If whisper-cli fails when invoked with -dtw, it logs a warning and falls back to standard execution."""
    import subprocess
    from engines.whisper_cpp import WhisperCppTranscriber

    invoked_cmds = []

    def mock_run(cmd, *args, **kwargs):
        invoked_cmds.append(list(cmd))
        class MockResult:
            pass

        res = MockResult()
        # If -dtw was passed, simulate failure (e.g. unknown option or unsupported build)
        if "-dtw" in cmd:
            res.returncode = 1
            res.stderr = "error: unknown argument -dtw"
            res.stdout = ""
            return res

        # Otherwise succeed and create the json file
        res.returncode = 0
        res.stderr = ""
        res.stdout = ""
        json_path = Path(cmd[cmd.index("-of") + 1] + ".json")
        sample_json = {
            "transcription": [
                {
                    "tokens": [
                        {"id": 1, "text": " Olá", "offsets": {"from": 0, "to": 500}, "p": 0.95}
                    ]
                }
            ]
        }
        json_path.write_text(json.dumps(sample_json), encoding="utf-8")
        return res

    monkeypatch.setattr(subprocess, "run", mock_run)

    transcriber = WhisperCppTranscriber(
        cli_path="whisper-cli",
        model_path="models/ggml-large-v3-turbo.bin",
        dtw_enabled=True,
    )
    audio_path = str(tmp_path / "test.wav")
    words = transcriber._transcribe_file(audio_path)

    assert len(words) == 1
    assert words[0].text == " Olá"
    assert len(invoked_cmds) == 2
    assert "-dtw" in invoked_cmds[0]
    assert "-dtw" not in invoked_cmds[1]


def test_qwen3_asr_and_vibevoice_satisfy_transcriber_protocol():
    """Verify both new engines strictly implement the Transcriber protocol."""
    from engines.qwen3_asr import Qwen3AsrTranscriber
    from engines.vibevoice import VibeVoiceTranscriber

    qwen = Qwen3AsrTranscriber(model_path="dummy")
    vibe = VibeVoiceTranscriber(model_path="dummy")

    assert isinstance(qwen, Transcriber)
    assert isinstance(vibe, Transcriber)
    assert getattr(vibe, "has_native_diarization", False) is True
    assert getattr(qwen, "has_native_diarization", False) is False


def test_make_transcriber_supports_qwen3_and_vibevoice():
    """Core constructs thin adapters without importing either Engine runtime."""
    from engines.isolated_python import IsolatedPythonTranscriber

    qwen = make_transcriber({
        "id": "test-qwen",
        "engine": "qwen3-asr",
        "model_path": "models/qwen",
        "language": "Portuguese",
    })
    assert isinstance(qwen, IsolatedPythonTranscriber)
    assert qwen.engine_id == "qwen3-asr"
    assert qwen.model_path == "models/qwen"
    assert qwen.options["language"] == "Portuguese"

    vibe = make_transcriber({
        "id": "test-vibe",
        "engine": "vibevoice",
        "model_path": "models/vibe",
    })
    assert isinstance(vibe, IsolatedPythonTranscriber)
    assert vibe.engine_id == "vibevoice"
    assert vibe.model_path == "models/vibe"


def test_vibevoice_segment_parsing_and_labels():
    """VibeVoice raw output is parsed into SPEAKER_XX labeled segments."""
    from engines.vibevoice import parse_segments_from_transcript

    raw_text = (
        "[Silence][Silence] "
        "Speaker 0: Oi pessoal, bom dia, tudo bem? "
        "Speaker 1: Bom dia! "
        "Speaker 0: Vamos iniciar a reunião."
    )
    segments = parse_segments_from_transcript(raw_text)

    assert len(segments) == 3
    assert segments[0]["speaker"] == "SPEAKER_00"
    assert segments[0]["text"] == "Oi pessoal, bom dia, tudo bem?"
    assert segments[1]["speaker"] == "SPEAKER_01"
    assert segments[1]["text"] == "Bom dia!"
    assert segments[2]["speaker"] == "SPEAKER_00"
    assert segments[2]["text"] == "Vamos iniciar a reunião."


def test_qwen3_word_overlap_stitching():
    """Qwen3 word stitcher detects overlapping words and removes duplicates."""
    from engines.qwen3_asr import Qwen3AsrTranscriber

    transcriber = Qwen3AsrTranscriber(model_path="dummy")
    w1 = [
        Word(start=0.0, end=1.0, text=" Olá"),
        Word(start=1.0, end=2.0, text=" pessoal"),
        Word(start=2.0, end=3.0, text=" tudo"),
        Word(start=3.0, end=4.0, text=" bem"),
    ]
    w2 = [
        Word(start=2.1, end=3.1, text=" tudo"),
        Word(start=3.1, end=4.1, text=" bem"),
        Word(start=4.1, end=5.0, text=" hoje"),
    ]

    stitched = transcriber._stitch_words(w1, w2)
    assert [w.text for w in stitched] == [" Olá", " pessoal", " tudo", " bem", " hoje"]


def test_engine_status_for_new_engines(tmp_path):
    """engine_status rejects missing and metadata-free checkpoints."""
    from engines import engine_status

    model_dir = tmp_path / "model"
    model_dir.mkdir()

    incomplete_qwen = {"engine": "qwen3-asr", "model_path": str(model_dir)}
    status = engine_status(incomplete_qwen)
    assert status["available"] is False
    assert status["state"] == "blocked"
    assert any(check["code"] == "checkpoint.primary.config" for check in status["checks"])

    missing_qwen = {"engine": "qwen3-asr", "model_path": str(tmp_path / "nonexistent")}
    status_miss = engine_status(missing_qwen)
    assert status_miss["available"] is False
    directory_check = next(
        check for check in status_miss["checks"]
        if check["code"] == "checkpoint.primary.directory"
    )
    assert directory_check["passed"] is False
    assert "not found" in directory_check["message"].lower()


@pytest.mark.parametrize(
    ("module_name", "class_name", "engine_name"),
    [
        ("engines.qwen3_asr", "Qwen3AsrTranscriber", "qwen3-asr"),
        ("engines.vibevoice", "VibeVoiceTranscriber", "vibevoice"),
    ],
)
@pytest.mark.parametrize(
    ("failure_stage", "failure"),
    [
        ("model", ValueError("unknown model type `qwen3_asr`")),
        ("model", RuntimeError("CUDA out of memory")),
        ("processor", RuntimeError("processor is incompatible")),
    ],
)
def test_optional_aligner_load_failure_is_transactional_and_warned_once(
    tmp_path, monkeypatch, caplog, module_name, class_name, engine_name, failure_stage, failure
):
    module = __import__(module_name, fromlist=[class_name])
    transcriber_class = getattr(module, class_name)
    aligner_path = tmp_path / "aligner"
    aligner_path.mkdir()
    processor = object()

    class ProcessorLoader:
        @staticmethod
        def from_pretrained(path):
            if failure_stage == "processor":
                raise failure
            return processor

    class ModelLoader:
        calls = 0

        @classmethod
        def from_pretrained(cls, path, **kwargs):
            cls.calls += 1
            raise failure

    monkeypatch.setitem(
        sys.modules,
        "transformers",
        types.SimpleNamespace(
            AutoProcessor=ProcessorLoader,
            AutoModelForTokenClassification=ModelLoader,
        ),
    )
    transcriber = transcriber_class(model_path="primary", aligner_path=str(aligner_path), device="cpu")

    with caplog.at_level(logging.WARNING):
        transcriber._ensure_aligner_loaded()
        transcriber._ensure_aligner_loaded()

    assert transcriber._aligner_processor is None
    assert transcriber._aligner_model is None
    assert str(failure) in transcriber._aligner_unavailable_reason
    warnings = [record.message for record in caplog.records if engine_name in record.message]
    assert len(warnings) == 1
    assert str(aligner_path) in warnings[0]
    assert "proportional" in warnings[0].lower()
    assert ModelLoader.calls == (0 if failure_stage == "processor" else 1)


def test_qwen3_proportional_fallback_produces_join_ready_ordered_words():
    from engines.qwen3_asr import Qwen3AsrTranscriber

    class Inputs(dict):
        def to(self, *_args):
            return self

    class Processor:
        def apply_transcription_request(self, **_kwargs):
            return Inputs(input_ids=np.zeros((1, 1), dtype=np.int64))

        def decode(self, *_args, **_kwargs):
            return "primeira segunda terceira"

    class Model:
        device = "cpu"
        dtype = None

        def generate(self, **_kwargs):
            return np.zeros((1, 2), dtype=np.int64)

    transcriber = Qwen3AsrTranscriber(model_path="primary", aligner_path=None, device="cpu")
    transcriber._asr_processor = Processor()
    transcriber._asr_model = Model()

    words = transcriber._transcribe_and_align_chunk(np.zeros(48000, dtype=np.float32), 2.0)

    assert [word.text for word in words] == [" primeira", " segunda", " terceira"]
    assert all(word.start <= word.end for word in words)
    assert all(before.end <= after.start for before, after in zip(words, words[1:]))
    assert all(word.alignment_score == 0.5 for word in words)


def test_vibevoice_proportional_fallback_produces_join_ready_ordered_words(monkeypatch):
    import engines.vibevoice as module

    class Model:
        def streaming_generate(self, **_kwargs):
            yield None, None, "Speaker 0: primeira segunda terceira"

    transcriber = module.VibeVoiceTranscriber(model_path="primary", aligner_path=None, device="cpu")
    transcriber._model = Model()
    transcriber._processor = types.SimpleNamespace(tokenizer=object())
    monkeypatch.setattr(module, "get_audio_duration", lambda _path: 3.0)
    monkeypatch.setattr(module, "load_audio_ffmpeg", lambda *_args, **_kwargs: np.zeros(48000, dtype=np.float32))

    words = transcriber.transcribe("meeting.wav")

    assert [word.text for word in words] == [" primeira", " segunda", " terceira"]
    assert all(word.start <= word.end for word in words)
    assert all(before.end <= after.start for before, after in zip(words, words[1:]))
    assert all(word.alignment_score < 0.98 for word in words)


@pytest.mark.parametrize(
    ("module_name", "class_name", "duration_function", "load_method"),
    [
        ("engines.qwen3_asr", "Qwen3AsrTranscriber", "get_audio_duration_seconds", "_ensure_asr_loaded"),
        ("engines.vibevoice", "VibeVoiceTranscriber", "get_audio_duration", "_ensure_model_loaded"),
    ],
)
def test_primary_model_load_failures_still_propagate(
    monkeypatch, module_name, class_name, duration_function, load_method
):
    module = __import__(module_name, fromlist=[class_name])
    transcriber = getattr(module, class_name)(model_path="primary", aligner_path=None, device="cpu")
    monkeypatch.setattr(module, duration_function, lambda _path: 1.0)

    def fail_primary_load():
        raise RuntimeError("primary model load failed")

    monkeypatch.setattr(transcriber, load_method, fail_primary_load)

    with pytest.raises(RuntimeError, match="primary model load failed"):
        transcriber.transcribe("meeting.wav")


def test_qwen3_primary_loader_uses_the_supported_qwen_asr_runtime(monkeypatch):
    import qwen_asr.core.transformers_backend as backend

    from engines.qwen3_asr import Qwen3AsrTranscriber

    processor = object()
    model = object()

    class ProcessorLoader:
        @staticmethod
        def from_pretrained(path):
            assert path == "primary"
            return processor

    class ModelLoader:
        @staticmethod
        def from_pretrained(path, **kwargs):
            assert path == "primary"
            assert kwargs["device_map"] == "cpu"
            return model

    monkeypatch.setattr(backend, "Qwen3ASRProcessor", ProcessorLoader)
    monkeypatch.setattr(backend, "Qwen3ASRForConditionalGeneration", ModelLoader)
    transcriber = Qwen3AsrTranscriber(model_path="primary", aligner_path=None, device="cpu")

    transcriber._ensure_asr_loaded()

    assert transcriber._asr_processor is processor
    assert transcriber._asr_model is model


