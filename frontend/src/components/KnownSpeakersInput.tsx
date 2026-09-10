import { useState, useRef } from "react";

interface KnownSpeakersInputProps {
  speakers: string[];
  onChange: (speakers: string[]) => void;
  placeholder?: string;
  disabled?: boolean;
}

export default function KnownSpeakersInput({
  speakers,
  onChange,
  placeholder = "Add speaker name (press Enter or comma)...",
  disabled = false,
}: KnownSpeakersInputProps) {
  const [inputValue, setInputValue] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  function addNames(raw: string) {
    const names = raw
      .split(/[,;\n]+/)
      .map((n) => n.trim())
      .filter(Boolean);

    if (names.length === 0) return;

    // Filter out case-insensitive duplicates while preserving order
    const currentLower = new Set(speakers.map((s) => s.toLowerCase()));
    const newItems: string[] = [];

    for (const name of names) {
      if (!currentLower.has(name.toLowerCase())) {
        currentLower.add(name.toLowerCase());
        newItems.push(name);
      }
    }

    if (newItems.length > 0) {
      onChange([...speakers, ...newItems]);
    }
    setInputValue("");
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Enter" || e.key === ",") {
      e.preventDefault();
      addNames(inputValue);
    } else if (e.key === "Backspace" && !inputValue && speakers.length > 0) {
      // Remove last speaker on backspace when input is empty
      e.preventDefault();
      onChange(speakers.slice(0, -1));
    }
  }

  function handleBlur() {
    if (inputValue.trim()) {
      addNames(inputValue);
    }
  }

  function handlePaste(e: React.ClipboardEvent<HTMLInputElement>) {
    const pasted = e.clipboardData.getData("text");
    if (pasted.includes(",") || pasted.includes(";") || pasted.includes("\n")) {
      e.preventDefault();
      addNames(pasted);
    }
  }

  function removeSpeaker(index: number) {
    onChange(speakers.filter((_, i) => i !== index));
  }

  function clearAll() {
    onChange([]);
    setInputValue("");
  }

  return (
    <div className="space-y-2.5">
      {/* Input row */}
      <div className="flex gap-2">
        <div className="relative flex-1">
          <input
            ref={inputRef}
            type="text"
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            onKeyDown={handleKeyDown}
            onBlur={handleBlur}
            onPaste={handlePaste}
            disabled={disabled}
            placeholder={placeholder}
            className="w-full bg-slate-800 border border-slate-700/50 rounded-xl px-4 py-2.5 text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-violet-500/50 text-sm disabled:opacity-50 disabled:cursor-not-allowed"
          />
        </div>
        <button
          type="button"
          onClick={() => addNames(inputValue)}
          disabled={disabled || !inputValue.trim()}
          className="px-4 py-2.5 bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-white border border-slate-700/50 rounded-xl text-sm font-medium transition disabled:opacity-40 disabled:cursor-not-allowed flex items-center gap-1.5"
        >
          <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
          </svg>
          <span>Add</span>
        </button>
      </div>

      {/* Speaker chips */}
      {speakers.length > 0 && (
        <div className="flex flex-wrap items-center gap-2 pt-1">
          {speakers.map((name, idx) => (
            <span
              key={`${name}-${idx}`}
              className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-medium bg-violet-500/15 text-violet-200 border border-violet-500/30 group hover:border-violet-400/50 transition-colors shadow-sm"
            >
              <span className="w-4 h-4 rounded-full bg-violet-500/30 text-[10px] font-semibold flex items-center justify-center text-violet-300 select-none">
                {name.charAt(0).toUpperCase()}
              </span>
              <span>{name}</span>
              {!disabled && (
                <button
                  type="button"
                  onClick={() => removeSpeaker(idx)}
                  className="w-3.5 h-3.5 rounded-full flex items-center justify-center text-violet-400 hover:text-white hover:bg-violet-500/30 transition ml-0.5"
                  title={`Remove ${name}`}
                >
                  <svg className="w-2.5 h-2.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M6 18L18 6M6 6l12 12" />
                  </svg>
                </button>
              )}
            </span>
          ))}

          {speakers.length > 1 && !disabled && (
            <button
              type="button"
              onClick={clearAll}
              className="text-[11px] text-slate-500 hover:text-slate-400 underline decoration-slate-600 transition ml-1"
            >
              Clear all
            </button>
          )}
        </div>
      )}
    </div>
  );
}
