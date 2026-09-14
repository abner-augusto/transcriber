import type { Preset } from "../types";

export function firstUsablePreset(presets: Preset[], excludedId?: string | null): Preset | undefined {
  return presets.find((preset) => preset.id !== excludedId && preset.state !== "blocked")
    || presets.find((preset) => preset.state !== "blocked");
}
