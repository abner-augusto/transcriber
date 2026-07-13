# No data leaves the machine

**Status**: accepted

The Transcriber processes private conversations, and the person running it is the only user. We
have decided that no Meeting data — audio, transcripts, Words, or Voice Profile embeddings — is
ever sent to a remote service. Every Engine runs locally.

## What this rule does *not* forbid

**Downloading model weights is not sending data.** The rule is about Meeting data flowing *out*, not
about artefacts flowing *in*. An Engine may fetch its weights over the network on first run, and may
require a credential to do so.

The live example is the Diarizer: `pyannote/speaker-diarization-3.1` is a *gated* HuggingFace repo,
so a HuggingFace token is needed to download it. That token is a download credential, not an
inference credential — once the weights are cached, diarization runs on the local GPU and works with
no network at all. This is compliant. Do not remove it.

(Note that pyannote also sells a hosted API. Using that *would* violate this ADR.)

## Consequences

- **Cloud ASR is out of scope.** Deepgram, AssemblyAI, and the hosted Whisper API are not
  candidate Engines, no matter how accurate. This is what justifies the Transcriber and Diarizer
  being *separate* ports rather than one combined "recognize" port: the engines that return an
  already-diarized transcript in a single call are all hosted services we will never use.
- **Cloud LLMs are out of scope.** The `claude-sonnet-4` and `gemini-flash-lite` Presets are
  removed.
- **A local LLM is permitted.** Ollama, llama.cpp, or anything else running on the same machine is
  compatible with this decision. See ADR-0002.
- The tool must remain fully functional with no network connection, once models are downloaded.
