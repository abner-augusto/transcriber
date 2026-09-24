import { useState } from "react";
import PresetTab from "./settings/PresetTab";
import PreferencesTab from "./settings/PreferencesTab";
import { usePresetEditor } from "./settings/usePresetEditor";
import { usePreferencesForm } from "./settings/usePreferencesForm";

interface Props {
  onClose: () => void;
}

export default function SettingsDialog({ onClose }: Props) {
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [tab, setTab] = useState<"presets" | "preferences">("presets");
  const presetEditor = usePresetEditor();
  const preferences = usePreferencesForm();
  const { settings } = presetEditor;

  async function handleSave() {
    setSaving(true);
    if (tab === "preferences") {
      await preferences.save();
    }
    setSaving(false);
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  }

  if (!settings) {
    return (
      <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50 p-4" onClick={onClose}>
        <div className="bg-slate-900 border border-slate-700/50 rounded-2xl shadow-2xl p-6 w-full max-w-2xl" onClick={(e) => e.stopPropagation()}>
          <div className="flex items-center justify-center py-8">
            <div className="w-5 h-5 border-2 border-violet-500/30 border-t-violet-500 rounded-full animate-spin" />
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50 p-4" onClick={onClose}>
      <div className="bg-slate-900 border border-slate-700/50 rounded-2xl shadow-2xl p-6 w-full max-w-2xl max-h-[90vh] flex flex-col" onClick={(e) => e.stopPropagation()}>
        <h2 className="text-xl font-bold text-white mb-4 flex-shrink-0">Settings</h2>

        <div className="flex bg-slate-800 rounded-xl p-1 mb-5 flex-shrink-0">
          {(["presets", "preferences"] as const).map((t) => (
            <button key={t} onClick={() => setTab(t)}
              className={`flex-1 py-2 rounded-lg text-sm font-medium transition-all capitalize ${tab === t ? "bg-slate-700 text-white shadow-sm" : "text-slate-400 hover:text-white"}`}>
              {t}
            </button>
          ))}
        </div>

        {/* One scroll container for both tabs, so switching tabs keeps the scroll offset. */}
        <div className="space-y-5 overflow-y-auto pr-1 flex-1">
          {tab === "presets" ? (
            <PresetTab settings={settings} editor={presetEditor} />
          ) : (
            <PreferencesTab form={preferences} />
          )}
        </div>

        <div className="flex items-center justify-end gap-3 mt-6">
          <button onClick={onClose}
            className="px-4 py-2 text-slate-400 hover:text-white hover:bg-slate-800 rounded-xl transition text-sm">
            Cancel
          </button>
          <button onClick={handleSave} disabled={saving}
            className="px-5 py-2 bg-violet-600 text-white rounded-xl font-medium hover:bg-violet-500 disabled:opacity-50 transition text-sm flex items-center gap-2">
            {saving ? (<><div className="w-3.5 h-3.5 border-2 border-white/30 border-t-white rounded-full animate-spin" />Saving...</>) : saved ? "Saved!" : "Save"}
          </button>
        </div>
      </div>
    </div>
  );
}
