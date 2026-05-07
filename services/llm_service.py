import json
import logging
import re
import requests
from config import settings

log = logging.getLogger(__name__)

CHUNK_SECONDS = 30
MAX_CHUNKS = 20  # Safety limit: 10 minutes max

class LLMService:
    def __init__(self, preset: dict | None = None):
        if preset:
            self.base_url = preset.get("base_url") or settings.llm_base_url
            self.api_key = preset.get("api_key") or settings.llm_api_key
            self.model = preset.get("model") or settings.llm_model
        else:
            self.base_url = settings.llm_base_url
            self.api_key = settings.llm_api_key
            self.model = settings.llm_model

    def is_configured(self) -> bool:
        """Check if the LLM service has a base URL configured."""
        return bool(self.base_url and self.base_url.strip())

    def _call(self, messages: list[dict], max_tokens: int = 1000) -> str:
        """Call the OpenAI-compatible LLM endpoint."""
        if not self.is_configured():
            raise RuntimeError("LLM service is not configured (missing LLM_BASE_URL)")

        headers = {
            "Content-Type": "application/json",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
            
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.1,
            "max_tokens": max_tokens,
        }
        
        # OpenRouter-specific optimizations
        if "openrouter.ai" in self.base_url:
            payload["transforms"] = [] # Example optimization
        
        url = f"{self.base_url.rstrip('/')}/chat/completions"
        
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=120)
            response.raise_for_status()
            return response.json()["choices"][0]["message"]["content"].strip()
        except Exception as e:
            log.error(f"LLM call failed at {url}: {e}")
            raise

    def _parse_json(self, content: str):
        """Extract JSON from LLM response, handling markdown code blocks and think tags."""
        # Strip Qwen3-style <think>...</think> blocks
        content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()

        # Try raw parse first
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            pass

        # Extract from markdown code blocks
        if "```" in content:
            parts = content.split("```")
            for part in parts:
                if part.strip().startswith("{") or part.strip().startswith("["):
                    block = part.strip()
                    if block.startswith("json"):
                        block = block[4:]
                    try:
                        return json.loads(block.strip())
                    except json.JSONDecodeError:
                        continue

        # Last resort: find first JSON object or array in the string
        decoder = json.JSONDecoder()
        for match in re.finditer(r'[\[{]', content):
            try:
                obj, _ = decoder.raw_decode(content, match.start())
                return obj
            except json.JSONDecodeError:
                continue

        raise ValueError(f"No valid JSON found in LLM response: {content[:200]}")

    def analyze_intro_iteratively(
        self,
        whisper_segments: list[dict],
        on_progress: callable = None,
    ) -> dict:
        """
        Send transcript to LLM in ~30s chunks. After each chunk, ask if the
        introduction phase is still ongoing. Stop when the LLM says it's done.
        """
        chunks = self._build_chunks(whisper_segments, CHUNK_SECONDS)

        if not chunks:
            return {"speaker_count": 0, "names": [], "intro_end_time": 0}

        messages = [
            {
                "role": "system",
                "content": (
                    "You are a meeting analyst. You receive a transcription of a meeting "
                    "in stages (chunk by chunk). Your task is to identify "
                    "the introduction phase - the part where participants introduce themselves. "
                    "For each new chunk, analyze if introductions are still ongoing "
                    "or if the meeting has moved on to other content.\n\n"
                    "ALWAYS respond with JSON in exactly this format:\n"
                    '{"intro_ongoing": true/false, '
                    '"speaker_count": <number of unique participants identified so far>, '
                    '"names": ["name1", "name2"], '
                    '"reasoning": "short explanation"}'
                ),
            }
        ]

        result = {"speaker_count": 0, "names": [], "intro_end_time": 0}

        for i, chunk in enumerate(chunks):
            if i >= MAX_CHUNKS:
                break

            chunk_text = chunk["text"]
            chunk_end = chunk["end_time"]

            messages.append({
                "role": "user",
                "content": (
                    f"Chunk {i + 1} (time {chunk['start_time']:.0f}s - {chunk_end:.0f}s):\n"
                    f"{chunk_text}\n\n"
                    f"Is the introduction phase still ongoing? "
                    f"How many unique participants have you identified so far?"
                ),
            })

            if on_progress:
                on_progress(f"Analyzing chunk {i + 1}/{len(chunks)} ({chunk_end:.0f}s)...")

            try:
                response_text = self._call(messages, max_tokens=500)
                messages.append({"role": "assistant", "content": response_text})

                data = self._parse_json(response_text)
                log.info(f"Intro chunk {i+1}: {data}")

                result["speaker_count"] = data.get("speaker_count", result["speaker_count"])
                result["names"] = data.get("names", result["names"])
                result["intro_end_time"] = chunk_end

                if not data.get("intro_ongoing", True):
                    log.info(f"Intro ended at {chunk_end:.0f}s with {result['speaker_count']} speakers")
                    break

            except Exception as e:
                log.warning(f"LLM chunk {i+1} failed: {e}")
                continue

        return result

    def _build_chunks(self, segments: list[dict], chunk_seconds: float) -> list[dict]:
        """Group whisper segments into time-based chunks."""
        if not segments:
            return []

        chunks = []
        current_texts = []
        chunk_start = segments[0].get("start", 0)
        chunk_end = chunk_start

        for seg in segments:
            seg_start = seg.get("start", 0)
            seg_end = seg.get("end", seg_start)
            text = seg.get("text", "").strip()
            if not text:
                continue

            if seg_start - chunk_start >= chunk_seconds and current_texts:
                chunks.append({
                    "text": " ".join(current_texts),
                    "start_time": chunk_start,
                    "end_time": chunk_end,
                })
                current_texts = []
                chunk_start = seg_start

            current_texts.append(text)
            chunk_end = seg_end

        if current_texts:
            chunks.append({
                "text": " ".join(current_texts),
                "start_time": chunk_start,
                "end_time": chunk_end,
            })

        return chunks

    def identify_speakers_from_intro(self, intro_text: str, known_names: list[str] | None = None) -> list[dict]:
        """
        Send intro transcript (with speaker labels) to LLM to map names.
        Returns list of {speaker_label, name}.
        """
        names_hint = ""
        if known_names:
            names_hint = f"\nKnown participants mentioned in the intro: {', '.join(known_names)}. Use these names when assigning speakers.\n"

        prompt = f"""Analyze this transcription from the beginning of a meeting.
Identify which speaker label corresponds to which person based on who is speaking and what is said.
{names_hint}
Transcription:
{intro_text}

Respond ONLY with a JSON array in this format:
[
  {{"speaker_label": "SPEAKER_00", "name": "Firstname Lastname"}},
  {{"speaker_label": "SPEAKER_01", "name": "Firstname Lastname"}}
]

If you cannot identify any names, respond with an empty array: []
Respond ONLY with JSON, no other text."""

        try:
            content = self._call([{"role": "user", "content": prompt}])
            return self._parse_json(content)
        except Exception:
            return []
