from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import presets
from engines import TRANSCRIBER_ENGINES, engine_status, probe_engine

router = APIRouter(prefix="/api/model-settings", tags=["model-settings"])


def _require_usable(preset: dict) -> dict:
    health = probe_engine(preset).to_dict()
    if health["state"] == "blocked":
        raise HTTPException(409, {"message": health["summary"], "health": health})
    return health


class CreatePreset(BaseModel):
    name: str
    engine: str
    model_path: str
    aligner_path: str | None = None
    language: str | None = None
    decoder: str | None = None
    device: str | None = None
    compute_type: str | None = None
    vad_filter: bool | None = None


class UpdatePreset(BaseModel):
    name: str | None = None
    engine: str | None = None
    model_path: str | None = None
    aligner_path: str | None = None
    language: str | None = None
    decoder: str | None = None
    device: str | None = None


class SetDefault(BaseModel):
    default_preset: str


@router.get("")
def get_model_settings():
    """Every Preset, whether it can actually run here, and which one is the default."""
    return {
        "presets": [{**p, **engine_status(p)} for p in presets.list_presets()],
        "default_preset": presets.default_preset_id(),
        "engines": TRANSCRIBER_ENGINES,
    }


@router.put("")
def set_default(body: SetDefault):
    preset = presets.get_preset(body.default_preset)
    if not preset:
        raise HTTPException(404, f"Preset not found: {body.default_preset}")
    _require_usable(preset)
    try:
        presets.set_default_preset(body.default_preset)
    except ValueError as e:
        raise HTTPException(404, str(e))
    return {"default_preset": presets.default_preset_id()}


@router.post("/presets")
def create_preset(body: CreatePreset):
    if body.engine not in TRANSCRIBER_ENGINES:
        raise HTTPException(400, f"Unknown engine '{body.engine}'. Known: {TRANSCRIBER_ENGINES}")

    preset = {k: v for k, v in body.model_dump().items() if v is not None}
    health = _require_usable(preset)
    try:
        return {**presets.create_preset(preset), **health}
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.put("/presets/{preset_id}")
def update_preset(preset_id: str, body: UpdatePreset):
    if body.engine and body.engine not in TRANSCRIBER_ENGINES:
        raise HTTPException(400, f"Unknown engine '{body.engine}'. Known: {TRANSCRIBER_ENGINES}")

    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    existing = presets.get_preset(preset_id)
    if not existing:
        raise HTTPException(404, "Preset not found")
    candidate = {**existing, **updates}
    health = _require_usable(candidate)
    try:
        return {**presets.update_preset(preset_id, updates), **health}
    except FileNotFoundError:
        raise HTTPException(404, "Preset not found")
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.delete("/presets/{preset_id}")
def delete_preset(preset_id: str):
    try:
        presets.delete_preset(preset_id)
    except FileNotFoundError:
        raise HTTPException(404, "Preset not found")
    return {"ok": True}
