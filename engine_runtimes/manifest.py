"""Load and validate the checked-in Python Engine runtime manifests."""

from __future__ import annotations

import argparse
import importlib
import importlib.metadata
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


MANIFEST_DIR = Path(__file__).with_name("manifests")

# An Engine runs in the runtime (manifest and virtual environment) of the same name,
# except where one is named after its model family rather than the Engine.
_ENGINE_RUNTIMES = {"nemotron-3-diarization": "nemotron-diarization"}


def runtime_for_engine(engine_id: str) -> str:
    return _ENGINE_RUNTIMES.get(engine_id, engine_id)
_ROOT_FIELDS = {
    "schema_version", "runtime_id", "python", "packages", "transformers",
    "sources", "torch", "model_types", "capabilities", "required_imports", "tested",
}
_TORCH_FIELDS = {"version", "cuda"}
_SOURCE_FIELDS = {"url", "commit"}
_CAPABILITY_FIELDS = {
    "required", "supported", "reason", "packages", "model_types", "required_imports"
}
_TESTED_FIELDS = {"python", "torch", "cuda", "transformers", "platform"}
_SPECIFIER = re.compile(r"^(==|!=|<=|>=|<|>)([A-Za-z0-9][A-Za-z0-9.+!_-]*)(?:,(==|!=|<=|>=|<|>)[A-Za-z0-9][A-Za-z0-9.+!_-]*)*$")


class ManifestError(ValueError):
    """An actionable runtime-manifest validation error."""


@dataclass(frozen=True)
class RuntimeManifest:
    runtime_id: str
    python: str
    packages: Mapping[str, str]
    sources: Mapping[str, Mapping[str, str]]
    transformers: str
    torch: Mapping[str, str]
    model_types: tuple[str, ...]
    capabilities: Mapping[str, Mapping[str, Any]]
    required_imports: tuple[str, ...]
    tested: Mapping[str, str]


def _require_fields(data: Mapping[str, Any], required: set[str], where: str) -> None:
    missing = sorted(required - data.keys())
    if missing:
        raise ManifestError(f"{where} is missing required field(s): {', '.join(missing)}")


def _reject_unknown(data: Mapping[str, Any], allowed: set[str], where: str) -> None:
    unknown = sorted(data.keys() - allowed)
    if unknown:
        raise ManifestError(f"{where} contains unknown field(s): {', '.join(unknown)}")


def _validate_specifier(value: Any, where: str) -> str:
    if not isinstance(value, str) or not _SPECIFIER.fullmatch(value):
        raise ManifestError(f"{where} must be a comma-separated version constraint such as '>=1.2,<2.0'")
    return value


def _string_tuple(value: Any, where: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value or not all(isinstance(item, str) and item for item in value):
        raise ManifestError(f"{where} must be a non-empty list of strings")
    return tuple(value)


def _string_tuple_allow_empty(value: Any, where: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise ManifestError(f"{where} must be a list of strings")
    return tuple(value)


def load_manifest(path_or_runtime: str | Path) -> RuntimeManifest:
    path = Path(path_or_runtime)
    if path.suffix != ".json":
        path = MANIFEST_DIR / f"{path}.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ManifestError(f"Cannot read runtime manifest {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ManifestError("runtime manifest root must be an object")
    _reject_unknown(data, _ROOT_FIELDS, "runtime manifest")
    _require_fields(data, _ROOT_FIELDS, "runtime manifest")
    if data["schema_version"] != 1:
        raise ManifestError(f"Unsupported runtime manifest schema_version {data['schema_version']!r}; expected 1")
    if not isinstance(data["runtime_id"], str) or not re.fullmatch(r"[a-z0-9-]+-v\d+", data["runtime_id"]):
        raise ManifestError("runtime_id must be stable and versioned, for example 'qwen3-asr-v1'")

    packages = data["packages"]
    if not isinstance(packages, dict) or not packages:
        raise ManifestError("packages must be a non-empty object")
    for name, specifier in packages.items():
        if not isinstance(name, str) or not name:
            raise ManifestError("package names must be non-empty strings")
        _validate_specifier(specifier, f"packages.{name}")

    sources = data["sources"]
    if not isinstance(sources, dict):
        raise ManifestError("sources must be an object")
    for name, source in sources.items():
        if name not in packages or not isinstance(source, dict):
            raise ManifestError(f"sources.{name} must describe a package declared in packages")
        _reject_unknown(source, _SOURCE_FIELDS, f"sources.{name}")
        _require_fields(source, _SOURCE_FIELDS, f"sources.{name}")
        if not isinstance(source["url"], str) or not source["url"].startswith("https://"):
            raise ManifestError(f"sources.{name}.url must be an HTTPS URL")
        if not isinstance(source["commit"], str) or not re.fullmatch(r"[0-9a-f]{40}", source["commit"]):
            raise ManifestError(f"sources.{name}.commit must be a full 40-character Git commit")

    torch = data["torch"]
    if not isinstance(torch, dict):
        raise ManifestError("torch must be an object")
    _reject_unknown(torch, _TORCH_FIELDS, "torch")
    _require_fields(torch, _TORCH_FIELDS, "torch")
    _validate_specifier(torch["version"], "torch.version")
    if not isinstance(torch["cuda"], str) or not torch["cuda"]:
        raise ManifestError("torch.cuda must be a non-empty compatibility description")

    capabilities = data["capabilities"]
    if not isinstance(capabilities, dict):
        raise ManifestError("capabilities must be an object")
    for name, capability in capabilities.items():
        if not isinstance(capability, dict):
            raise ManifestError(f"capabilities.{name} must be an object")
        _reject_unknown(capability, _CAPABILITY_FIELDS, f"capabilities.{name}")
        _require_fields(capability, _CAPABILITY_FIELDS, f"capabilities.{name}")
        if not isinstance(capability["required"], bool):
            raise ManifestError(f"capabilities.{name}.required must be boolean")
        if not isinstance(capability["supported"], bool):
            raise ManifestError(f"capabilities.{name}.supported must be boolean")
        if not isinstance(capability["reason"], str) or not capability["reason"]:
            raise ManifestError(f"capabilities.{name}.reason must be a non-empty string")
        if not isinstance(capability["packages"], dict):
            raise ManifestError(f"capabilities.{name}.packages must be an object")
        for package, specifier in capability["packages"].items():
            _validate_specifier(specifier, f"capabilities.{name}.packages.{package}")
        _string_tuple(capability["model_types"], f"capabilities.{name}.model_types")
        _string_tuple_allow_empty(capability["required_imports"], f"capabilities.{name}.required_imports")

    tested = data["tested"]
    if not isinstance(tested, dict):
        raise ManifestError("tested must be an object")
    _reject_unknown(tested, _TESTED_FIELDS, "tested")
    _require_fields(tested, _TESTED_FIELDS, "tested")
    if not all(isinstance(value, str) and value for value in tested.values()):
        raise ManifestError("all tested matrix values must be non-empty strings")

    return RuntimeManifest(
        runtime_id=data["runtime_id"], python=_validate_specifier(data["python"], "python"),
        packages=packages, sources=sources,
        transformers=_validate_specifier(data["transformers"], "transformers"),
        torch=torch, model_types=_string_tuple(data["model_types"], "model_types"),
        capabilities=capabilities,
        required_imports=_string_tuple(data["required_imports"], "required_imports"), tested=tested,
    )


def _version_key(version: str) -> tuple[int, ...]:
    match = re.match(r"^(\d+(?:\.\d+)*)", version)
    if not match:
        raise ManifestError(f"cannot compare non-numeric version {version!r}")
    return tuple(int(part) for part in match.group(1).split("."))


def version_satisfies(version: str, specifier: str) -> bool:
    actual = _version_key(version)
    for clause in specifier.split(","):
        match = re.fullmatch(r"(==|!=|<=|>=|<|>)(.+)", clause)
        if not match:
            raise ManifestError(f"malformed version constraint {specifier!r}")
        op, expected_text = match.groups()
        expected = _version_key(expected_text)
        width = max(len(actual), len(expected))
        left, right = actual + (0,) * (width - len(actual)), expected + (0,) * (width - len(expected))
        matches = {"==": left == right, "!=": left != right, "<": left < right, "<=": left <= right, ">": left > right, ">=": left >= right}[op]
        if not matches:
            return False
    return True


def validate_environment(manifest: RuntimeManifest, *, include_optional: bool = False) -> list[str]:
    errors: list[str] = []
    python_version = ".".join(map(str, sys.version_info[:3]))
    if not version_satisfies(python_version, manifest.python):
        errors.append(f"Python {python_version} does not satisfy {manifest.python}")
    requirements = dict(manifest.packages)
    if include_optional:
        for capability in manifest.capabilities.values():
            if capability["supported"]:
                requirements.update(capability["packages"])
    for package, specifier in requirements.items():
        try:
            installed = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            errors.append(f"missing package {package} ({specifier} required)")
            continue
        if not version_satisfies(installed, specifier):
            errors.append(f"package {package} {installed} does not satisfy {specifier}")
            continue
        source = manifest.sources.get(package)
        if source:
            direct_url_text = importlib.metadata.distribution(package).read_text("direct_url.json")
            try:
                direct_url = json.loads(direct_url_text) if direct_url_text else {}
            except json.JSONDecodeError:
                direct_url = {}
            commit = direct_url.get("vcs_info", {}).get("commit_id")
            editable = direct_url.get("dir_info", {}).get("editable", False)
            if editable or commit != source["commit"]:
                errors.append(
                    f"package {package} is not installed from immutable commit {source['commit']}"
                )
    imports = list(manifest.required_imports)
    if include_optional:
        imports.extend(
            module for cap in manifest.capabilities.values() if cap["supported"]
            for module in cap["required_imports"]
        )
    for module in imports:
        try:
            module_name, separator, attribute = module.partition(":")
            imported = importlib.import_module(module_name)
            if separator and not hasattr(imported, attribute):
                raise ImportError(f"{module_name} has no attribute {attribute}")
        except Exception as exc:
            errors.append(f"required import {module!r} failed: {exc}")
    return errors


def validate_checkpoint(manifest: RuntimeManifest, checkpoint: str | Path, *, capability: str | None = None) -> list[str]:
    config_path = Path(checkpoint) / "config.json"
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"cannot read checkpoint metadata {config_path}: {exc}"]
    supported = manifest.model_types
    if capability is not None:
        if capability not in manifest.capabilities:
            return [f"unknown optional capability {capability!r}"]
        capability_contract = manifest.capabilities[capability]
        if not capability_contract["supported"]:
            return [f"optional capability {capability!r} is unsupported: {capability_contract['reason']}"]
        supported = tuple(capability_contract["model_types"])
    model_type = config.get("model_type")
    if model_type not in supported:
        return [f"checkpoint model_type {model_type!r} is incompatible; expected one of {', '.join(supported)}"]
    return []


def validate_presets(manifest: RuntimeManifest, presets_dir: str | Path) -> list[str]:
    """Validate metadata for locally available checkpoints configured by Presets."""
    errors: list[str] = []
    engine = manifest.runtime_id.rsplit("-v", 1)[0]
    for preset_path in sorted(Path(presets_dir).glob("*.json")):
        try:
            preset = json.loads(preset_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"cannot read Preset {preset_path}: {exc}")
            continue
        if preset.get("engine") != engine:
            continue
        configured_model_path = preset.get("model_path")
        model_path = Path(configured_model_path) if configured_model_path else None
        if model_path is not None and model_path.is_dir():
            errors.extend(
                f"Preset {preset_path.name}: {error}"
                for error in validate_checkpoint(manifest, model_path)
            )
        configured_aligner_path = preset.get("aligner_path")
        aligner_path = Path(configured_aligner_path) if configured_aligner_path else None
        if aligner_path is not None and aligner_path.is_dir():
            errors.extend(
                f"Preset {preset_path.name}: {error}"
                for error in validate_checkpoint(
                    manifest, aligner_path, capability="forced-alignment"
                )
            )
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("runtime", choices=("qwen3-asr", "vibevoice", "nemotron-diarization"))
    parser.add_argument("--checkpoint")
    parser.add_argument("--capability")
    parser.add_argument("--include-optional", action="store_true")
    parser.add_argument("--presets-dir")
    args = parser.parse_args()
    manifest = load_manifest(args.runtime)
    errors = validate_environment(manifest, include_optional=args.include_optional)
    if args.checkpoint:
        errors.extend(validate_checkpoint(manifest, args.checkpoint, capability=args.capability))
    if args.presets_dir:
        errors.extend(validate_presets(manifest, args.presets_dir))
    if errors:
        print("\n".join(f"ERROR: {error}" for error in errors), file=sys.stderr)
        return 1
    unsupported = [name for name, cap in manifest.capabilities.items() if not cap["supported"]]
    suffix = f"; unsupported optional capabilities: {', '.join(unsupported)}" if unsupported else ""
    print(f"{manifest.runtime_id}: compatible{suffix}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
