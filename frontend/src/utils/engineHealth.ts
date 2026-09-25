import type { Preset } from "../types";

export type EngineHealthState = Preset["state"];

/** The status dot beside an Engine's name, for Presets and Diarizers alike. */
export function engineHealthDot(state: EngineHealthState): string {
  return state === "ready"
    ? "bg-emerald-400 ring-2 ring-emerald-400/20"
    : state === "degraded"
      ? "bg-amber-400 ring-2 ring-amber-400/20"
      : "bg-red-400 ring-2 ring-red-400/20";
}

export function firstUsablePreset(presets: Preset[], excludedId?: string | null): Preset | undefined {
  return presets.find((preset) => preset.id !== excludedId && preset.state !== "blocked")
    || presets.find((preset) => preset.state !== "blocked");
}
