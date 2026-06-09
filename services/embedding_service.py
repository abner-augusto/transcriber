import numpy as np
import torch
import soundfile as sf
from pathlib import Path
import huggingface_hub

# Patch: speechbrain 1.0.3 passes use_auth_token which was removed in newer huggingface_hub
_orig_hf_download = huggingface_hub.hf_hub_download
def _compat_hf_download(*args, **kwargs):
    kwargs.pop("use_auth_token", None)
    return _orig_hf_download(*args, **kwargs)
huggingface_hub.hf_hub_download = _compat_hf_download


REPO_ID = "speechbrain/spkrec-ecapa-voxceleb"
MODEL_FILES = ["hyperparams.yaml", "embedding_model.ckpt", "mean_var_norm_emb.ckpt", "label_encoder.txt"]


class EmbeddingService:
    _model = None
    _cpu_model = None

    @classmethod
    def _ensure_model_files(cls) -> Path:
        """Download model files if not cached."""
        cache_dir = Path.home() / ".cache" / "speechbrain" / "spkrec-ecapa-voxceleb"
        cache_dir.mkdir(parents=True, exist_ok=True)

        for filename in MODEL_FILES:
            local_path = cache_dir / filename
            if not local_path.exists():
                print(f"[Embedding] Downloading {filename}...")
                downloaded = huggingface_hub.hf_hub_download(
                    repo_id=REPO_ID,
                    filename=filename,
                    local_dir=str(cache_dir),
                )
        return cache_dir

    @classmethod
    def _build_model(cls, device: str):
        from speechbrain.inference.speaker import EncoderClassifier
        save_dir = cls._ensure_model_files()
        model = EncoderClassifier.from_hparams(
            source=str(save_dir),
            savedir=str(save_dir),
            run_opts={"device": device},
        )
        model.mods.eval()
        for p in model.mods.parameters():
            p.requires_grad_(False)
        return model

    @classmethod
    def get_model(cls):
        if cls._model is None:
            device = "cuda:0" if torch.cuda.is_available() else "cpu"
            cls._model = cls._build_model(device)
            print(f"[Embedding] ECAPA-TDNN model loaded on {device}")
        return cls._model

    @classmethod
    def get_cpu_model(cls):
        if cls._cpu_model is None:
            cls._cpu_model = cls._build_model("cpu")
            print("[Embedding] ECAPA-TDNN CPU model loaded")
        return cls._cpu_model

    def extract_embedding(self, audio_path: str, force_cpu: bool = False) -> np.ndarray:
        """Extract speaker embedding from audio file.

        force_cpu=True bypasses GPU entirely — use for rare, latency-tolerant
        operations (e.g. saving a speaker profile) so they can't be killed by
        GPU pressure from concurrent transcription/diarization work.
        """
        model = self.get_cpu_model() if force_cpu else self.get_model()

        data, sr = sf.read(audio_path, dtype="float32", always_2d=True)
        # soundfile returns (samples, channels) — transpose to (channels, samples)
        signal = torch.from_numpy(data.T)

        if sr != 16000:
            import torchaudio.functional as F
            signal = F.resample(signal, sr, 16000)

        if signal.shape[0] > 1:
            signal = signal.mean(dim=0, keepdim=True)

        with torch.no_grad():
            embedding = model.encode_batch(signal)

        return embedding.squeeze().detach().cpu().numpy()

    def cosine_similarity(self, emb1: np.ndarray, emb2: np.ndarray) -> float:
        """Compute cosine similarity between two embeddings."""
        dot = np.dot(emb1, emb2)
        norm = np.linalg.norm(emb1) * np.linalg.norm(emb2)
        if norm == 0:
            return 0.0
        return float(dot / norm)
