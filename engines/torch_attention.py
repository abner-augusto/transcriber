"""Attention backend selection for CUDA Python Engines.

On Windows the CUDA wheels ship without Flash-Attention and, on Blackwell
(sm_120) parts, PyTorch disables the memory-efficient kernel at runtime. Math
SDPA is then the default for every forward pass: it materialises the full score
matrix and launches the attention as many tiny kernels.

Fused cuDNN attention is available on those same wheels and is a clear win for
the forced aligner, which attends over a few thousand positions in one pass —
measured on a 300 s chunk: 0.3-0.6 s and ~2 GB less peak VRAM than math.

It is deliberately *not* made the global default: for one-token decode, cuDNN
is slower per call (VibeVoice streaming measured 0.90x vs 3.01x RTF), and a
fresh process pays ~37 s of cuDNN autotune on its first decode. So the choice
stays scoped to the forward passes where it was measured to help.
"""

import logging
from contextlib import contextmanager

import torch

log = logging.getLogger(__name__)


@contextmanager
def fused_attention_first():
    """Prefer the fused cuDNN kernel for the enclosed forward pass.

    Math is excluded inside the scope (PyTorch ranks it above cuDNN), so callers
    keep a plain retry as the fallback for shapes cuDNN rejects.
    """
    if not torch.cuda.is_available():
        yield
        return
    try:
        from torch.nn.attention import SDPBackend, sdpa_kernel
    except ImportError:  # pragma: no cover - torch without the attention namespace
        yield
        return
    with sdpa_kernel([SDPBackend.CUDNN_ATTENTION]):
        yield


def fused_attention_unavailable(exc: BaseException) -> bool:
    """True when a RuntimeError came from having no fused attention kernel left."""
    message = str(exc)
    return "No available kernel" in message or "no available kernel" in message


def drop_single_sample_padding_mask(inputs):
    """Drop a redundant all-ones attention mask from a single-sample batch.

    Padding is the only thing a decoder-only attention mask encodes, and these
    Engines always transcribe one audio file at a time, so the mask carries no
    information while it does push SDPA off the fused kernels.
    """
    try:
        batch_size = inputs["input_ids"].shape[0]
    except (KeyError, AttributeError, IndexError):
        return inputs
    if batch_size == 1:
        inputs.pop("attention_mask", None)
    return inputs
