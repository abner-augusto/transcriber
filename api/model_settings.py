from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from pathlib import Path

from model_config import get_model_config
from config import settings

router = APIRouter(prefix="/api/model-settings", tags=["model-settings"])


class UpdateAssignments(BaseModel):
    assignments: dict[str, str]


class CreatePreset(BaseModel):
    name: str
    model: str
    base_url: str


def _whisper_info() -> dict:
    return {
        "model": Path(settings.whisper_model_path).name,
        "small_model": Path(settings.whisper_small_model_path).name,
    }


@router.get("")
def get_model_settings():
    mgr = get_model_config()
    mgr.reload()
    return {
        "presets": mgr.get_presets(type_filter="llm"),
        "assignments": {k: v for k, v in mgr.get_assignments().items() if k not in ("transcription", "live_transcription")},
        "whisper": _whisper_info(),
    }


@router.put("")
def update_model_settings(body: UpdateAssignments):
    mgr = get_model_config()
    mgr.update_assignments(body.assignments)
    return {
        "presets": mgr.get_presets(type_filter="llm"),
        "assignments": {k: v for k, v in mgr.get_assignments().items() if k not in ("transcription", "live_transcription")},
        "whisper": _whisper_info(),
    }


@router.post("/presets")
def create_preset(body: CreatePreset):
    mgr = get_model_config()
    preset = mgr.create_preset({"name": body.name, "model": body.model, "base_url": body.base_url})
    return preset


@router.delete("/presets/{preset_id}")
def delete_preset(preset_id: str):
    mgr = get_model_config()
    try:
        mgr.delete_preset(preset_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Preset not found")
    return {"ok": True}
