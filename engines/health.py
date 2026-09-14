"""Fast, side-effect-free health probes for transcription Engine Presets."""

from __future__ import annotations

import ast
import ctypes
import hashlib
import importlib.metadata
import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

from config import settings
from engine_runtimes.manifest import ManifestError, RuntimeManifest, load_manifest, version_satisfies


HealthState = Literal["ready", "degraded", "blocked"]
_HEALTH_CACHE: dict[str, "EngineHealth"] = {}


@dataclass(frozen=True)
class EngineCheck:
    code: str
    required: bool
    passed: bool
    message: str


@dataclass(frozen=True)
class EngineHealth:
    state: HealthState
    summary: str
    checks: tuple[EngineCheck, ...]
    fingerprint: str

    def to_dict(self) -> dict:
        result = asdict(self)
        result["available"] = self.state != "blocked"
        result["reason"] = None if self.state == "ready" else self.summary
        return result


def _check(code: str, required: bool, passed: bool, message: str) -> EngineCheck:
    return EngineCheck(code=code, required=required, passed=passed, message=message)


def _normalized_distribution_name(name: str) -> str:
    return name.lower().replace("_", "-").replace(".", "-")


def _runtime_site_packages(executable: Path) -> tuple[Path, ...]:
    """Locate a venv's package roots without running or importing from it."""
    venv = executable.parent.parent
    windows = venv / "Lib" / "site-packages"
    posix = tuple(sorted((venv / "lib").glob("python*/site-packages")))
    return tuple(path for path in (windows, *posix) if path.is_dir())


def _runtime_distributions(executable: Path) -> dict[str, importlib.metadata.Distribution]:
    result = {}
    for distribution in importlib.metadata.distributions(path=[str(path) for path in _runtime_site_packages(executable)]):
        name = distribution.metadata.get("Name")
        if name:
            result[_normalized_distribution_name(name)] = distribution
    return result


def _distribution_version(name: str, distributions: dict[str, importlib.metadata.Distribution]) -> str | None:
    distribution = distributions.get(_normalized_distribution_name(name))
    return distribution.version if distribution is not None else None


def _module_source(distribution_name: str, module_name: str, distributions: dict[str, importlib.metadata.Distribution]) -> Path | None:
    """Locate module source from distribution metadata without importing it."""
    distribution = distributions.get(_normalized_distribution_name(distribution_name))
    if distribution is None:
        return None
    relative = Path(*module_name.split("."))
    candidates = (relative.with_suffix(".py"), relative / "__init__.py")
    files = distribution.files or ()
    normalized = {Path(str(item).replace("\\", "/")): item for item in files}
    for candidate in candidates:
        item = normalized.get(candidate)
        if item is not None:
            path = Path(distribution.locate_file(item))
            return path if path.is_file() else None
    return None


def _source_defines(path: Path, attribute: str) -> bool:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, SyntaxError):
        return False
    for node in tree.body:
        if (
            isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == attribute
        ):
            return True
        if isinstance(node, ast.ImportFrom) and any(
            (alias.asname or alias.name) == attribute for alias in node.names
        ):
            return True
        if isinstance(node, ast.Import) and any(
            (alias.asname or alias.name.rsplit(".", 1)[-1]) == attribute
            for alias in node.names
        ):
            return True
    return False


def _config(path: Path) -> tuple[dict | None, str]:
    config_path = path / "config.json"
    try:
        raw = config_path.read_bytes()
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise ValueError("root is not an object")
        return value, hashlib.sha256(raw).hexdigest()
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        return None, f"unreadable:{exc}"


def _checkpoint_checks(path_text: str | None, model_types: tuple[str, ...], *, required: bool, prefix: str) -> tuple[list[EngineCheck], str]:
    checks: list[EngineCheck] = []
    path = Path(path_text) if path_text else None
    exists = bool(path and path.is_dir())
    checks.append(_check(f"{prefix}.directory", required, exists, f"Checkpoint directory {'found' if exists else 'not found'}: {path_text or '(not configured)'}"))
    if not exists or path is None:
        return checks, "missing"
    config, config_hash = _config(path)
    checks.append(_check(f"{prefix}.config", required, config is not None, "Checkpoint config.json is readable" if config else "Checkpoint config.json is missing or malformed"))
    if config is None:
        return checks, config_hash
    model_type = config.get("model_type")
    compatible = model_type in model_types
    checks.append(_check(f"{prefix}.model_type", required, compatible, f"Checkpoint model_type {model_type!r} {'is compatible' if compatible else f'is incompatible; expected one of {', '.join(model_types)}'}"))

    index_paths = sorted(path.glob("*.index.json"))
    missing: list[str] = []
    malformed = False
    for index_path in index_paths:
        try:
            index = json.loads(index_path.read_text(encoding="utf-8"))
            shards = set(index.get("weight_map", {}).values())
            if not shards:
                malformed = True
            missing.extend(sorted(name for name in shards if not (path / name).is_file()))
        except (OSError, json.JSONDecodeError, AttributeError):
            malformed = True
    passed = not malformed and not missing
    detail = "Declared checkpoint shards are present"
    if malformed:
        detail = "Checkpoint shard index is malformed"
    elif missing:
        detail = f"Missing declared checkpoint shards: {', '.join(missing[:3])}"
    checks.append(_check(f"{prefix}.shards", required, passed, detail))
    index_facts = ",".join(f"{p.name}:{p.stat().st_mtime_ns}:{p.stat().st_size}" for p in index_paths)
    return checks, f"{config_hash}:{index_facts}:{','.join(missing)}"


def _cuda_available() -> bool:
    if os.name != "nt":
        return Path("/dev/nvidiactl").exists()
    try:
        ctypes.WinDLL("nvcuda.dll")
        return True
    except OSError:
        return False


def _manifest_probe(preset: dict, manifest: RuntimeManifest) -> tuple[list[EngineCheck], list[str]]:
    checks: list[EngineCheck] = []
    engine = preset.get("engine")
    runtime_text = settings.qwen3_asr_python if engine == "qwen3-asr" else settings.vibevoice_python
    runtime = Path(runtime_text)
    runtime_exists = runtime.is_file()
    checks.append(_check("runtime.executable", True, runtime_exists, f"Dedicated runtime {'found' if runtime_exists else 'not found'}: {runtime_text}"))
    runtime_fact = f"{runtime.resolve()}:{runtime.stat().st_size}:{runtime.stat().st_mtime_ns}" if runtime_exists else f"missing:{runtime_text}"
    facts = [manifest.runtime_id, runtime_fact]
    runtime_distributions = _runtime_distributions(runtime) if runtime_exists else {}
    for package, specifier in manifest.packages.items():
        installed = _distribution_version(package, runtime_distributions)
        passed = installed is not None and version_satisfies(installed, specifier)
        checks.append(_check(f"runtime.package.{package}", True, passed, f"{package} {installed or 'is not installed'}; required {specifier}"))
        facts.append(f"{package}={installed}")
        source = manifest.sources.get(package)
        if source and installed is not None:
            try:
                direct_text = runtime_distributions[_normalized_distribution_name(package)].read_text("direct_url.json")
                direct = json.loads(direct_text) if direct_text else {}
            except (KeyError, OSError, json.JSONDecodeError):
                direct = {}
            commit = direct.get("vcs_info", {}).get("commit_id")
            immutable = commit == source["commit"] and not direct.get("dir_info", {}).get("editable", False)
            checks.append(_check(f"runtime.source.{package}", True, immutable, f"{package} {'matches' if immutable else 'does not match'} immutable commit {source['commit']}"))
            facts.append(f"{package}-commit={commit}")

    primary_distribution = next((name for name in manifest.sources if name in manifest.packages), next(iter(manifest.packages)))
    for import_contract in manifest.required_imports:
        module, separator, attribute = import_contract.partition(":")
        source = _module_source(primary_distribution, module, runtime_distributions)
        passed = source is not None and (not separator or _source_defines(source, attribute))
        checks.append(_check(f"runtime.import.{module}.{attribute or 'module'}", True, passed, f"Required class {import_contract} {'is present' if passed else 'was not found'}"))

    checkpoint_checks, checkpoint_fact = _checkpoint_checks(preset.get("model_path"), manifest.model_types, required=True, prefix="checkpoint.primary")
    checks.extend(checkpoint_checks)
    facts.append(checkpoint_fact)

    for name, capability in manifest.capabilities.items():
        configured = bool(preset.get("aligner_path")) if name == "forced-alignment" else True
        if not configured:
            continue
        required = bool(capability["required"])
        if not capability["supported"]:
            checks.append(_check(f"capability.{name}.runtime", required, False, f"{capability['reason']} Fallback uses approximate timestamps."))
            facts.append(f"{name}=unsupported")
            continue
        optional_checks, optional_fact = _checkpoint_checks(preset.get("aligner_path"), tuple(capability["model_types"]), required=required, prefix=f"capability.{name}")
        checks.extend(optional_checks)
        facts.append(optional_fact)

    device = preset.get("device", "auto")
    cuda = _cuda_available()
    device_ok = device != "cuda" or cuda
    checks.append(_check("device.cuda", True, device_ok, f"Requested device is {device}; CUDA driver {'is available' if cuda else 'is not available'}"))
    facts.extend((f"device={device}", f"cuda={cuda}", f"cuda-contract={manifest.torch['cuda']}"))
    return checks, facts


def _legacy_probe(preset: dict) -> tuple[list[EngineCheck], list[str]]:
    engine = preset.get("engine")
    model_path = preset.get("model_path") or ""
    checks: list[EngineCheck] = []
    if engine == "faster-whisper":
        try:
            installed = importlib.metadata.version("faster-whisper")
        except importlib.metadata.PackageNotFoundError:
            installed = None
        checks.append(_check("runtime.package.faster-whisper", True, installed is not None, f"faster-whisper {installed or 'is not installed'}"))
        local = model_path.startswith((".", "/", "\\")) or (len(model_path) > 1 and model_path[1] == ":")
        model_ok = bool(model_path) and (not local or Path(model_path).exists())
    else:
        cli = {"whisper.cpp": settings.whisper_cli_path, "parakeet.cpp": settings.parakeet_cli_path}.get(engine)
        checks.append(_check("runtime.executable", True, bool(cli and Path(cli).is_file()), f"{engine} executable {'found' if cli and Path(cli).is_file() else 'not found'}: {cli or '(unknown Engine)'}"))
        model_ok = bool(model_path and Path(model_path).exists())
    checks.append(_check("checkpoint.primary.directory", True, model_ok, f"Model {'found' if model_ok else 'not found'}: {model_path or '(not configured)'}"))
    return checks, [str(engine), model_path, str(Path(model_path).stat().st_mtime_ns if model_ok and Path(model_path).exists() else "missing")]


def probe_engine(preset: dict, deep: bool = False) -> EngineHealth:
    """Inspect local metadata only. ``deep`` is reserved for Plan 005."""
    del deep
    engine = preset.get("engine")
    try:
        if engine in ("qwen3-asr", "vibevoice"):
            checks, facts = _manifest_probe(preset, load_manifest(engine))
        else:
            checks, facts = _legacy_probe(preset)
    except ManifestError as exc:
        checks, facts = [_check("runtime.manifest", True, False, str(exc))], [str(engine), str(exc)]
    required_failures = [item for item in checks if item.required and not item.passed]
    optional_failures = [item for item in checks if not item.required and not item.passed]
    state: HealthState = "blocked" if required_failures else "degraded" if optional_failures else "ready"
    failures = required_failures or optional_failures
    summary = "Engine is ready" if not failures else failures[0].message
    fingerprint = hashlib.sha256("\n".join(facts).encode("utf-8")).hexdigest()
    cached = _HEALTH_CACHE.get(fingerprint)
    if cached is not None:
        return cached
    health = EngineHealth(state=state, summary=summary, checks=tuple(checks), fingerprint=fingerprint)
    _HEALTH_CACHE[fingerprint] = health
    return health
