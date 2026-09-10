import time, torch
from qwen_asr.core.transformers_backend import Qwen3ASRForConditionalGeneration, Qwen3ASRProcessor

model_path = r"C:\Users\abner\_repos\_local-ai\models\Qwen3-ASR-1.7B-hf"
print("Loading with device_map='cuda' and dtype=torch.bfloat16...", flush=True)
t0 = time.perf_counter()
model = Qwen3ASRForConditionalGeneration.from_pretrained(
    model_path,
    dtype=torch.bfloat16,
    device_map="cuda",
)
t1 = time.perf_counter()
print(f"Model loaded in {t1-t0:.2f}s!", flush=True)
print(f"Allocated VRAM: {torch.cuda.memory_allocated() / (1024*1024):.1f} MB", flush=True)
print(f"Reserved VRAM: {torch.cuda.memory_reserved() / (1024*1024):.1f} MB", flush=True)
print("Device of first param:", next(model.parameters()).device, flush=True)
