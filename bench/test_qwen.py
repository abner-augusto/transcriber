import time, torch
from qwen_asr.core.transformers_backend import Qwen3ASRForConditionalGeneration, Qwen3ASRProcessor

model_path = r"C:\Users\abner\_repos\_local-ai\models\Qwen3-ASR-1.7B-hf"
print("Testing clean load with meta-fix...", flush=True)
t0 = time.perf_counter()
model = Qwen3ASRForConditionalGeneration.from_pretrained(
    model_path,
    dtype=torch.bfloat16,
)
print("Model loaded on CPU! Moving to CUDA...", flush=True)
model = model.to("cuda")
t1 = time.perf_counter()
print(f"Success! Model loaded and moved to CUDA in {t1-t0:.2f}s!", flush=True)
print(f"Allocated VRAM: {torch.cuda.memory_allocated() / (1024*1024):.1f} MB", flush=True)
print(f"Reserved VRAM: {torch.cuda.memory_reserved() / (1024*1024):.1f} MB", flush=True)
