import subprocess
import numpy as np
import torch
from transformers import AutoProcessor, AutoModelForMultimodalLM, AutoModelForTokenClassification

asr_id = r"C:\Users\abner\_repos\_local-ai\models\Qwen3-ASR-1.7B-hf"
aln_id = r"C:\Users\abner\_repos\_local-ai\models\Qwen3-ForcedAligner-0.6B-hf"

# 1. Load 10s of test.mp3
cmd = ["ffmpeg", "-v", "error", "-t", "10", "-i", "test.mp3", "-f", "f32le", "-ar", "16000", "-ac", "1", "-"]
proc = subprocess.Popen(cmd, stdout=subprocess.PIPE)
audio = np.frombuffer(proc.communicate()[0], dtype=np.float32)

# 2. Transcribe
proc_asr = AutoProcessor.from_pretrained(asr_id)
model_asr = AutoModelForMultimodalLM.from_pretrained(asr_id, dtype=torch.bfloat16, device_map="cuda")
inputs = proc_asr.apply_transcription_request(audio=audio, language="Portuguese").to("cuda", torch.bfloat16)
with torch.no_grad():
    out = model_asr.generate(**inputs, max_new_tokens=256)
gen_ids = out[:, inputs["input_ids"].shape[1]:]
text = proc_asr.decode(gen_ids[0], return_format="transcription_only").strip()
print("Transcript:", text)

del model_asr
torch.cuda.empty_cache()

# 3. Align
proc_aln = AutoProcessor.from_pretrained(aln_id)
model_aln = AutoModelForTokenClassification.from_pretrained(aln_id, dtype=torch.bfloat16, device_map="cuda")
aln_inputs, word_lists = proc_aln.prepare_forced_aligner_inputs(audio=audio, transcript=text, language="Portuguese")
aln_inputs = aln_inputs.to("cuda", torch.bfloat16)
with torch.no_grad():
    res = model_aln(**aln_inputs)
ts = proc_aln.decode_forced_alignment(
    logits=res.logits,
    input_ids=aln_inputs["input_ids"],
    word_lists=word_lists,
    timestamp_token_id=model_aln.config.timestamp_token_id,
)[0]

print("Aligned words (sample):")
for item in ts[:10]:
    print(f"  {item['text']:<15} {item['start_time']:>6.2f}s -> {item['end_time']:>6.2f}s")
