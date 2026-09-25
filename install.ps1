# Install the local Transcriber runtime.
$ErrorActionPreference = "Stop"
$ProjectRoot = $PSScriptRoot
Set-Location $ProjectRoot

function Assert-NativeSuccess($Step) {
    if ($LASTEXITCODE -ne 0) { throw "$Step failed with exit code $LASTEXITCODE" }
}

foreach ($tool in @("git", "python", "node", "npm", "cmake", "ffmpeg", "uv")) {
    if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) {
        throw "Required tool '$tool' was not found. Install Python 3.11+, Node.js 18+, CMake, FFmpeg, Git, and uv."
    }
}

$whisperDir = Join-Path (Split-Path $ProjectRoot -Parent) "whisper.cpp"
$whisperBin = Join-Path $whisperDir "build\bin\Release\whisper-cli.exe"
if (-not (Test-Path $whisperBin)) {
    if (-not (Test-Path $whisperDir)) {
        git clone https://github.com/ggerganov/whisper.cpp.git $whisperDir
        Assert-NativeSuccess "whisper.cpp clone"
    }
    Push-Location $whisperDir
    $cuda = if (Get-Command nvidia-smi -ErrorAction SilentlyContinue) { "-DGGML_CUDA=ON" } else { "" }
    if ($cuda) { cmake -B build -G "Visual Studio 17 2022" $cuda }
    else { cmake -B build -G "Visual Studio 17 2022" }
    Assert-NativeSuccess "whisper.cpp configuration"
    cmake --build build --config Release --parallel 8
    Assert-NativeSuccess "whisper.cpp build"
    Pop-Location
}

$parakeetDir = Join-Path (Split-Path $ProjectRoot -Parent) "parakeet.cpp"
$parakeetBin = Join-Path $parakeetDir "build\examples\cli\Release\parakeet-cli.exe"
if (-not (Test-Path $parakeetBin)) {
    if (-not (Test-Path $parakeetDir)) {
        git clone --recursive https://github.com/mudler/parakeet.cpp $parakeetDir
        Assert-NativeSuccess "parakeet.cpp clone"
    }
    Push-Location $parakeetDir
    if (Get-Command nvidia-smi -ErrorAction SilentlyContinue) {
        cmake -B build -G "Visual Studio 17 2022" -A x64 -DPARAKEET_GGML_CUDA=ON
    } else {
        cmake -B build -G "Visual Studio 17 2022" -A x64
    }
    Assert-NativeSuccess "parakeet.cpp configuration"
    cmake --build build --config Release --parallel 8
    Assert-NativeSuccess "parakeet.cpp build"
    Pop-Location
}

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    uv venv --python python .venv
    Assert-NativeSuccess "application virtual environment creation"
}
uv sync --locked --extra dev
Assert-NativeSuccess "application dependency sync"
if (Get-Command nvidia-smi -ErrorAction SilentlyContinue) {
    uv pip install --reinstall --python .venv\Scripts\python.exe torch==2.11.0 torchaudio==2.11.0 --index-url https://download.pytorch.org/whl/cu128
    Assert-NativeSuccess "CUDA PyTorch installation"
}
New-Item -ItemType Directory -Force -Path "models\parakeet" | Out-Null
& ".venv\Scripts\python.exe" -c "from huggingface_hub import hf_hub_download; hf_hub_download(repo_id='mudler/parakeet-cpp-gguf', filename='tdt-0.6b-v3-q4_k.gguf', local_dir='models/parakeet')"
if ($LASTEXITCODE -ne 0) { throw "Parakeet model download failed" }

foreach ($engineRuntime in @("qwen3-asr", "vibevoice")) {
    $runtimeDir = Join-Path "venv-engines" $engineRuntime
    $runtimePython = Join-Path $runtimeDir "Scripts\python.exe"
    if (-not (Test-Path $runtimePython)) {
        uv venv --python .venv\Scripts\python.exe $runtimeDir
        Assert-NativeSuccess "$engineRuntime environment creation"
    }
    if (Get-Command nvidia-smi -ErrorAction SilentlyContinue) {
        uv pip install --reinstall --python $runtimePython torch==2.11.0 torchaudio==2.11.0 --index-url https://download.pytorch.org/whl/cu128
        Assert-NativeSuccess "$engineRuntime CUDA PyTorch installation"
    } else {
        uv pip install --python $runtimePython torch==2.11.0 torchaudio==2.11.0
        Assert-NativeSuccess "$engineRuntime PyTorch installation"
    }
    uv pip install --python $runtimePython -r "requirements/engines/$engineRuntime.txt"
    Assert-NativeSuccess "$engineRuntime dependency installation"
    & $runtimePython -m engine_runtimes.manifest $engineRuntime --include-optional --presets-dir model_presets
    if ($LASTEXITCODE -ne 0) { throw "$engineRuntime runtime validation failed" }
}

# Work around speechbrain's Unix-only inspect.py path check on Windows.
$sbImportUtils = ".venv\Lib\site-packages\speechbrain\utils\importutils.py"
if (Test-Path $sbImportUtils) {
    $content = Get-Content $sbImportUtils -Raw
    $pattern = 'if importer_frame is not None and importer_frame.filename.endswith\(\s*"/inspect\.py"\s*\):'
    $replacement = @'
if importer_frame is not None and (
            importer_frame.filename.endswith("/inspect.py")
            or importer_frame.filename.endswith("\\inspect.py")
        ):
'@
    $content = [regex]::Replace($content, $pattern, $replacement, 1)
    Set-Content $sbImportUtils $content -Encoding UTF8 -NoNewline
}

Push-Location frontend
npm ci
Assert-NativeSuccess "frontend dependency installation"
npm run build
Assert-NativeSuccess "frontend build"
Pop-Location

if (-not (Test-Path ".env")) {
    $whisperPath = $whisperBin -replace '\\', '/'
    @"
DATABASE_URL=sqlite:///./storage/transcriber.db
STORAGE_PATH=./storage
WHISPER_CLI_PATH=$whisperPath
PARAKEET_CLI_PATH=../parakeet.cpp/build/examples/cli/Release/parakeet-cli.exe
HF_AUTH_TOKEN=
"@ | Set-Content -Path ".env" -Encoding UTF8
}

Write-Host "Install complete. Set HF_AUTH_TOKEN in .env if speaker diarization is needed, then run .\start.ps1."
