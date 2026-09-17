"""GPU memory management and model unloading utilities.

Ensures GPU VRAM is released after transcription, forced alignment, diarization,
and speaker naming stages, preventing persistent VRAM hoarding in Celery workers.
"""

import gc
import logging

log = logging.getLogger(__name__)


def release_gpu_memory() -> None:
    """Run garbage collection and flush CUDA / MPS caching allocators."""
    gc.collect()
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.ipc_collect()
        elif hasattr(torch, "mps") and hasattr(torch.mps, "empty_cache"):
            torch.mps.empty_cache()
    except Exception as exc:
        log.debug(f"[gpu_memory] release_gpu_memory failed: {exc}")


def unload_all_engines() -> None:
    """Unload all resident models (Faster-Whisper, Pyannote, MMS-FA, ECAPA-TDNN) and flush GPU memory."""
    # 1. Faster-Whisper
    try:
        from engines.faster_whisper import FasterWhisperTranscriber

        FasterWhisperTranscriber.unload()
    except Exception as exc:
        log.debug(f"[gpu_memory] Unloading FasterWhisperTranscriber failed: {exc}")

    # 2. Pyannote
    try:
        from engines.pyannote import PyannoteDiarizer

        PyannoteDiarizer.unload()
    except Exception as exc:
        log.debug(f"[gpu_memory] Unloading PyannoteDiarizer failed: {exc}")

    # 3. MMS CTC Aligner
    try:
        from engines.alignment import MMSCTCAligner

        MMSCTCAligner.unload()
    except Exception as exc:
        log.debug(f"[gpu_memory] Unloading MMSCTCAligner failed: {exc}")

    # 4. SpeechBrain ECAPA-TDNN Embedding
    try:
        from services.embedding_service import EmbeddingService

        EmbeddingService.unload()
    except Exception as exc:
        log.debug(f"[gpu_memory] Unloading EmbeddingService failed: {exc}")

    # 5. Flush GPU allocator caches
    release_gpu_memory()
    log.info("[gpu_memory] All resident models unloaded and GPU VRAM freed.")
