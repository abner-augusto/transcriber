import { useEffect, useState } from "react";
import type { ModelSettings, Preset } from "../../types";
import { getModelSettings, createModelPreset, updateModelPreset, deleteModelPreset, setDefaultPreset } from "../../api";
import { engineMeta } from "../../engineMetadata";

/**
 * The Preset list and the add/edit Preset form of the Settings dialog.
 *
 * Owned by the dialog, not the Presets tab, so an open form survives switching tabs.
 */
export function usePresetEditor() {
  const [settings, setSettings] = useState<ModelSettings | null>(null);
  const [showAddPreset, setShowAddPreset] = useState(false);
  const [editingPresetId, setEditingPresetId] = useState<string | null>(null);
  const [newName, setNewName] = useState("");
  const [newEngine, setNewEngine] = useState("parakeet.cpp");
  const [newModelPath, setNewModelPath] = useState("");
  const [newAlignerPath, setNewAlignerPath] = useState("");
  const [newLanguage, setNewLanguage] = useState("");
  const [newDecoder, setNewDecoder] = useState("tdt");
  const [newDevice, setNewDevice] = useState("cuda");
  const [addError, setAddError] = useState("");
  const [defaultSaving, setDefaultSaving] = useState<string | null>(null);

  useEffect(() => {
    loadSettings();
  }, []);

  async function loadSettings() {
    const data = await getModelSettings();
    setSettings(data);
    if (data.engines.length > 0 && !editingPresetId) {
      // The primary Engines (ADR-0007) come first.
      const initialEngine = data.engines.includes("parakeet.cpp")
        ? "parakeet.cpp"
        : data.engines.includes("faster-whisper")
        ? "faster-whisper"
        : data.engines[0];
      setNewEngine(initialEngine);
      applyEngineDefaults(initialEngine);
    }
  }

  function applyEngineDefaults(engine: string) {
    const meta = engineMeta(engine);
    setNewDevice(meta.defaultDevice || "cuda");
    setNewLanguage(meta.defaultLanguage || "");
    if (engine === "parakeet.cpp") setNewDecoder("tdt");
  }

  function handleEngineChange(engine: string) {
    setNewEngine(engine);
    setAddError("");
    applyEngineDefaults(engine);
  }

  function resetPresetForm() {
    setEditingPresetId(null);
    setNewName("");
    setNewModelPath("");
    setNewAlignerPath("");
    setNewLanguage("");
    setNewDecoder("tdt");
    setNewDevice("cuda");
    setAddError("");
  }

  function startEditPreset(preset: Preset) {
    setEditingPresetId(preset.id);
    setNewName(preset.name);
    setNewEngine(preset.engine);
    setNewModelPath(preset.model_path);
    setNewAlignerPath(preset.aligner_path || "");
    setNewLanguage(preset.language || "");
    setNewDecoder(preset.decoder || "tdt");
    setNewDevice(preset.device || "cuda");
    setAddError("");
    setShowAddPreset(true);
  }

  function cancelPresetForm() {
    setShowAddPreset(false);
    resetPresetForm();
  }

  async function handleSavePreset() {
    const trimmedName = newName.trim();
    const trimmedModelPath = newModelPath.trim();

    if (!trimmedName || !trimmedModelPath) {
      setAddError("Preset name and model path are required.");
      return;
    }
    setAddError("");

    const meta = engineMeta(newEngine);

    const payload = {
      name: trimmedName,
      engine: newEngine,
      model_path: trimmedModelPath,
      aligner_path: meta.supportsAligner && newAlignerPath.trim() ? newAlignerPath.trim() : undefined,
      language: meta.supportsLanguage && newLanguage.trim() ? newLanguage.trim() : undefined,
      device: meta.supportsDevice && newDevice.trim() ? newDevice.trim() : undefined,
      decoder: meta.supportsDecoder ? newDecoder : undefined,
    };

    try {
      if (editingPresetId) {
        await updateModelPreset(editingPresetId, payload);
      } else {
        await createModelPreset(payload);
      }
      cancelPresetForm();
      const data = await getModelSettings();
      setSettings(data);
    } catch (err: any) {
      const detail = err?.response?.data?.detail;
      setAddError(detail?.message || detail || "Failed to save preset");
    }
  }

  async function handleDeletePreset(id: string) {
    const preset = settings?.presets.find((p) => p.id === id);
    if (!confirm(`Delete preset "${preset?.name}"?`)) return;
    try {
      await deleteModelPreset(id);
      if (editingPresetId === id) cancelPresetForm();
      const data = await getModelSettings();
      setSettings(data);
    } catch (err: any) {
      alert(err?.response?.data?.detail || "Failed to delete preset");
    }
  }

  async function handleSetDefault(id: string) {
    if (!settings || settings.default_preset === id) return;
    setDefaultSaving(id);
    try {
      const { default_preset } = await setDefaultPreset(id);
      setSettings({ ...settings, default_preset });
    } catch (err: any) {
      const detail = err?.response?.data?.detail;
      alert(detail?.message || detail || "Failed to set default preset");
    } finally {
      setDefaultSaving(null);
    }
  }

  return {
    settings,
    showAddPreset, setShowAddPreset,
    editingPresetId,
    newName, setNewName,
    newEngine,
    newModelPath, setNewModelPath,
    newAlignerPath, setNewAlignerPath,
    newLanguage, setNewLanguage,
    newDecoder, setNewDecoder,
    newDevice, setNewDevice,
    addError,
    defaultSaving,
    handleEngineChange,
    resetPresetForm,
    startEditPreset,
    cancelPresetForm,
    handleSavePreset,
    handleDeletePreset,
    handleSetDefault,
  };
}

export type PresetEditor = ReturnType<typeof usePresetEditor>;
