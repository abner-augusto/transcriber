"""Vocabulary Profiles API — CRUD for reusable, named lists of Vocabulary terms."""

import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import preferences

router = APIRouter(prefix="/api/preferences/vocabulary-profiles", tags=["vocabulary-profiles"])


class CreateProfileRequest(BaseModel):
    name: str
    terms: str


class UpdateProfileRequest(BaseModel):
    name: str | None = None
    terms: str | None = None


@router.get("")
def list_profiles():
    """List all saved vocabulary profiles."""
    return [profile.model_dump() for profile in preferences.load().vocabulary_profiles]


@router.post("")
def create_profile(req: CreateProfileRequest):
    """Create a new vocabulary profile."""
    name = req.name.strip()
    terms = req.terms.strip()
    if not name:
        raise HTTPException(400, "Profile name is required")
    if not terms:
        raise HTTPException(400, "Terms are required")

    prefs = preferences.load()
    profiles = [profile.model_dump() for profile in prefs.vocabulary_profiles]

    # Prevent duplicate names (case-insensitive)
    for p in profiles:
        if p["name"].lower() == name.lower():
            raise HTTPException(400, f"Profile '{name}' already exists")

    profile = {"id": str(uuid.uuid4()), "name": name, "terms": terms[:2000]}
    profiles.append(profile)
    preferences.update({"vocabulary_profiles": profiles})
    return profile


@router.put("/{profile_id}")
def update_profile(profile_id: str, req: UpdateProfileRequest):
    """Update an existing vocabulary profile."""
    prefs = preferences.load()
    profiles = [profile.model_dump() for profile in prefs.vocabulary_profiles]

    idx = next((i for i, p in enumerate(profiles) if p["id"] == profile_id), None)
    if idx is None:
        raise HTTPException(404, "Profile not found")

    if req.name is not None:
        name = req.name.strip()
        if not name:
            raise HTTPException(400, "Profile name cannot be empty")
        # Check for name collision with other profiles
        for i, p in enumerate(profiles):
            if i != idx and p["name"].lower() == name.lower():
                raise HTTPException(400, f"Profile '{name}' already exists")
        profiles[idx]["name"] = name

    if req.terms is not None:
        terms = req.terms.strip()
        if not terms:
            raise HTTPException(400, "Terms cannot be empty")
        profiles[idx]["terms"] = terms[:2000]

    preferences.update({"vocabulary_profiles": profiles})
    return profiles[idx]


@router.delete("/{profile_id}")
def delete_profile(profile_id: str):
    """Delete a vocabulary profile."""
    prefs = preferences.load()
    profiles = [profile.model_dump() for profile in prefs.vocabulary_profiles]

    idx = next((i for i, p in enumerate(profiles) if p["id"] == profile_id), None)
    if idx is None:
        raise HTTPException(404, "Profile not found")

    profiles.pop(idx)
    preferences.update({"vocabulary_profiles": profiles})
    return {"ok": True}
