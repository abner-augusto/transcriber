#!/usr/bin/env bash
set -euo pipefail

for tool in git python3 node npm cmake ffmpeg uv; do
  command -v "$tool" >/dev/null 2>&1 || {
    echo "Required tool '$tool' was not found. Install Python 3.11+, Node.js 18+, CMake, FFmpeg, Git, and uv." >&2
    exit 1
  }
done

project_root="$(cd "$(dirname "$0")" && pwd)"
cd "$project_root"
whisper_dir="$(dirname "$project_root")/whisper.cpp"
if [ ! -x "$whisper_dir/build/bin/whisper-cli" ]; then
  [ -d "$whisper_dir" ] || git clone https://github.com/ggerganov/whisper.cpp.git "$whisper_dir"
  cd "$whisper_dir"
  if [ "$(uname -s)" = "Darwin" ]; then
    cmake -B build -DGGML_METAL=ON
  elif command -v nvidia-smi >/dev/null 2>&1; then
    cmake -B build -DGGML_CUDA=ON
  else
    cmake -B build
  fi
  cmake --build build --config Release -j "$(getconf _NPROCESSORS_ONLN 2>/dev/null || sysctl -n hw.ncpu)"
  cd "$project_root"
fi

parakeet_dir="$(dirname "$project_root")/parakeet.cpp"
if [ ! -x "$parakeet_dir/build/examples/cli/parakeet-cli" ]; then
  [ -d "$parakeet_dir" ] || git clone --recursive https://github.com/mudler/parakeet.cpp "$parakeet_dir"
  cd "$parakeet_dir"
  if [ "$(uname -s)" = "Darwin" ]; then
    cmake -B build -DPARAKEET_GGML_METAL=ON
  elif command -v nvidia-smi >/dev/null 2>&1; then
    cmake -B build -DPARAKEET_GGML_CUDA=ON
  else
    cmake -B build
  fi
  cmake --build build --config Release -j "$(getconf _NPROCESSORS_ONLN 2>/dev/null || sysctl -n hw.ncpu)"
  cd "$project_root"
fi

[ -x .venv/bin/python ] || uv venv --python python3 .venv
uv sync --locked --extra dev
if [ "$(uname -s)" = "Linux" ] && command -v nvidia-smi >/dev/null 2>&1; then
  uv pip install --reinstall --python .venv/bin/python torch==2.11.0 torchaudio==2.11.0 --index-url https://download.pytorch.org/whl/cu128
fi
mkdir -p models/parakeet
.venv/bin/python -c "from huggingface_hub import hf_hub_download; hf_hub_download(repo_id='mudler/parakeet-cpp-gguf', filename='tdt-0.6b-v3-q4_k.gguf', local_dir='models/parakeet')"

for engine_runtime in qwen3-asr vibevoice; do
  runtime_dir="venv-engines/$engine_runtime"
  runtime_python="$runtime_dir/bin/python"
  [ -x "$runtime_python" ] || uv venv --python .venv/bin/python "$runtime_dir"
  if [ "$(uname -s)" = "Linux" ] && command -v nvidia-smi >/dev/null 2>&1; then
    uv pip install --reinstall --python "$runtime_python" torch==2.11.0 torchaudio==2.11.0 --index-url https://download.pytorch.org/whl/cu128
  else
    uv pip install --python "$runtime_python" torch==2.11.0 torchaudio==2.11.0
  fi
  uv pip install --python "$runtime_python" -r "requirements/engines/$engine_runtime.txt"
  "$runtime_python" -m engine_runtimes.manifest "$engine_runtime" --include-optional --presets-dir model_presets
done

npm --prefix frontend ci
npm --prefix frontend run build

if [ ! -f .env ]; then
  cat > .env <<EOF
DATABASE_URL=sqlite:///./storage/transcriber.db
STORAGE_PATH=./storage
WHISPER_CLI_PATH=$whisper_dir/build/bin/whisper-cli
PARAKEET_CLI_PATH=$parakeet_dir/build/examples/cli/parakeet-cli
HF_AUTH_TOKEN=
EOF
fi

echo "Install complete. Set HF_AUTH_TOKEN in .env if speaker diarization is needed, then run ./start.sh."
