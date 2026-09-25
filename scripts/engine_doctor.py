"""Report local Engine health and explicitly opted-in smoke results."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
from pathlib import Path

from engines.health import probe_engine
from presets import list_presets


PACKAGES = ("faster-whisper", "qwen-asr", "vibevoice", "transformers", "torch", "torchaudio")


def _version(package):
    try:
        return importlib.metadata.version(package)
    except importlib.metadata.PackageNotFoundError:
        return None


def validate_report(report):
    """Validate the stable v1 shape before either output format is emitted."""
    if set(report) != {"schema_version", "packages", "presets", "blocked"}:
        raise ValueError("doctor report has unexpected root fields")
    if report["schema_version"] != 1 or not isinstance(report["blocked"], bool):
        raise ValueError("doctor report schema_version/blocked fields are invalid")
    if not isinstance(report["packages"], dict) or not isinstance(report["presets"], list):
        raise ValueError("doctor report packages/presets fields are invalid")
    for item in report["presets"]:
        if not {"id", "name", "engine", "health"}.issubset(item):
            raise ValueError("doctor Preset entry is incomplete")
        health = item["health"]
        if health.get("state") not in {"ready", "degraded", "blocked"}:
            raise ValueError("doctor health state is invalid")
        if not isinstance(health.get("fingerprint"), str) or not isinstance(health.get("checks"), (list, tuple)):
            raise ValueError("doctor health contract is invalid")


def build_report(selected=(), tier="metadata", audio=None, opted_in=False):
    presets = list_presets()
    known = {preset["id"] for preset in presets}
    unknown = sorted(set(selected) - known)
    if unknown:
        raise ValueError("unknown Preset(s): " + ", ".join(unknown))
    if tier != "metadata" and not opted_in:
        raise ValueError("load/inference doctor tiers require --run-engine-smoke")
    if tier != "metadata" and not selected:
        raise ValueError("load/inference doctor tiers require at least one --preset")
    if tier == "inference" and not audio:
        raise ValueError("inference doctor tier requires --audio or ENGINE_SMOKE_AUDIO")

    entries = []
    for preset in presets:
        health = probe_engine(preset).to_dict()
        entry = {"id": preset["id"], "name": preset.get("name", preset["id"]), "engine": preset["engine"], "health": health}
        if preset["id"] in selected and tier != "metadata":
            from scripts.engine_smoke import infer_preset, load_preset

            try:
                entry["smoke"] = load_preset(preset) if tier == "load" else infer_preset(preset, Path(audio))
            except Exception as exc:
                entry["smoke"] = {"status": "failed", "code": "engine.smoke.failed", "message": f"{type(exc).__name__}: {exc}"}
        entries.append(entry)
    report = {"schema_version": 1, "packages": {name: _version(name) for name in PACKAGES}, "presets": entries, "blocked": any(item["health"]["state"] == "blocked" or item.get("smoke", {}).get("status") == "failed" for item in entries)}
    validate_report(report)
    return report


def _human(report):
    lines = ["Transcriber Engine doctor", "", "Packages:"]
    lines.extend(f"  {name}: {version or 'not installed'}" for name, version in report["packages"].items())
    lines.append("\nPresets:")
    for item in report["presets"]:
        health = item["health"]
        lines.append(f"  [{health['state'].upper()}] {item['id']} ({item['engine']}): {health['summary']} [{health['fingerprint'][:12]}]")
        if "smoke" in item:
            lines.append(f"    smoke: {item['smoke']['status']}")
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="emit schema-validated JSON")
    parser.add_argument("--tier", choices=("metadata", "load", "inference"), default="metadata")
    parser.add_argument("--preset", action="append", default=[])
    parser.add_argument("--audio", default=os.environ.get("ENGINE_SMOKE_AUDIO"))
    parser.add_argument("--run-engine-smoke", action="store_true")
    args = parser.parse_args(argv)
    try:
        report = build_report(args.preset, args.tier, args.audio, args.run_engine_smoke)
    except ValueError as exc:
        parser.error(str(exc))
    print(json.dumps(report, indent=2) if args.json else _human(report))
    return 1 if report["blocked"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
