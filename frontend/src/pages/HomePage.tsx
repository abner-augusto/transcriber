import { useEffect, useState, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { listMeetings, createMeeting, deleteMeeting, searchSegments } from "../api";
import type { SearchResult } from "../api";
import { useStore } from "../store";

const STATUS_LABELS: Record<string, { text: string; color: string; dot: string }> = {
  uploaded: { text: "Ready", color: "bg-sky-500/10 text-sky-400 ring-1 ring-sky-500/20", dot: "bg-sky-400" },
  processing: { text: "Processing...", color: "bg-amber-500/10 text-amber-400 ring-1 ring-amber-500/20", dot: "bg-amber-400 animate-pulse" },
  recording: { text: "Recording", color: "bg-red-500/10 text-red-400 ring-1 ring-red-500/20", dot: "bg-red-400 animate-pulse" },
  finalizing: { text: "Finalizing...", color: "bg-amber-500/10 text-amber-400 ring-1 ring-amber-500/20", dot: "bg-amber-400 animate-pulse" },
  completed: { text: "Done", color: "bg-emerald-500/10 text-emerald-400 ring-1 ring-emerald-500/20", dot: "bg-emerald-400" },
  failed: { text: "Failed", color: "bg-red-500/10 text-red-400 ring-1 ring-red-500/20", dot: "bg-red-400" },
};

function formatDuration(seconds: number | null): string {
  if (!seconds) return "-";
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

function formatDate(dateStr: string): string {
  const d = new Date(dateStr);
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

export default function HomePage() {
  const navigate = useNavigate();
  const { meetings, setMeetings } = useStore();
  const [showUpload, setShowUpload] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [title, setTitle] = useState("");
  const [minSpeakers, setMinSpeakers] = useState("");
  const [maxSpeakers, setMaxSpeakers] = useState("");
  const [vocabulary, setVocabulary] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);
  const [dragOver, setDragOver] = useState(false);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);

  // Error feedback
  const [error, setError] = useState<string | null>(null);

  // Search
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState<SearchResult[]>([]);
  const [searching, setSearching] = useState(false);
  const searchTimerRef = useRef<number>(0);

  function handleSearchChange(value: string) {
    setSearchQuery(value);
    clearTimeout(searchTimerRef.current);
    if (!value.trim()) {
      setSearchResults([]);
      return;
    }
    searchTimerRef.current = window.setTimeout(async () => {
      setSearching(true);
      try {
        const results = await searchSegments(value.trim());
        setSearchResults(results);
      } catch {
        setSearchResults([]);
      } finally {
        setSearching(false);
      }
    }, 300);
  }

  useEffect(() => {
    loadMeetings();
  }, []);

  async function loadMeetings() {
    const data = await listMeetings();
    setMeetings(data);
  }

  async function handleUpload() {
    const file = selectedFile;
    if (!file || !title.trim()) return;

    setUploading(true);
    try {
      const form = new FormData();
      form.append("file", file);
      form.append("title", title.trim());
      if (minSpeakers) form.append("min_speakers", minSpeakers);
      if (maxSpeakers) form.append("max_speakers", maxSpeakers);
      if (vocabulary.trim()) form.append("vocabulary", vocabulary.trim());

      const meeting = await createMeeting(form);
      setError(null);
      setShowUpload(false);
      resetDialog();
      navigate(`/meetings/${meeting.id}`);
    } catch (err: any) {
      const msg = err?.response?.data?.detail || err?.message || "Upload failed";
      setError(msg);
    } finally {
      setUploading(false);
    }
  }

  function resetDialog() {
    setTitle("");
    setSelectedFile(null);
    setMinSpeakers("");
    setMaxSpeakers("");
    setVocabulary("");
    setError(null);
  }

  async function handleDelete(e: React.MouseEvent, id: string) {
    e.stopPropagation();
    if (!window.confirm("Delete this recording? This cannot be undone.")) return;
    try {
      await deleteMeeting(id);
      loadMeetings();
    } catch (err: any) {
      setError(err?.response?.data?.detail || "Failed to delete meeting");
    }
  }

  function handleDrop(e: React.DragEvent) {
    e.preventDefault();
    setDragOver(false);
    const file = e.dataTransfer.files[0];
    if (file) {
      setSelectedFile(file);
      if (!title) setTitle(file.name.replace(/\.[^/.]+$/, ""));
    }
  }

  return (
    <main className="max-w-5xl mx-auto px-6 py-10">
      {/* Hero section */}
      <div className="mb-10">
        <div className="flex items-end justify-between">
          <div>
            <h1 className="text-3xl font-bold text-white tracking-tight">Meetings</h1>
            <p className="text-slate-400 mt-1">Upload audio for automatic transcription</p>
          </div>
          <button
            onClick={() => setShowUpload(true)}
            className="px-5 py-2.5 bg-gradient-to-r from-violet-600 to-indigo-600 text-white rounded-xl font-medium hover:from-violet-500 hover:to-indigo-500 transition-all shadow-lg shadow-violet-500/25 hover:shadow-violet-500/40 active:scale-[0.98]"
          >
            <span className="flex items-center gap-2">
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
              </svg>
              New transcription
            </span>
          </button>
        </div>
      </div>

      {/* Upload dialog */}
      {showUpload && (
        <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50" onClick={() => { setShowUpload(false); resetDialog(); }}>
          <div className="bg-slate-900 border border-slate-700/50 rounded-2xl shadow-2xl p-6 w-full max-w-lg" onClick={(e) => e.stopPropagation()}>
            <h2 className="text-xl font-bold text-white mb-5">New transcription</h2>

            {/* File upload area */}
            <div
                className={`relative border-2 border-dashed rounded-xl p-8 text-center mb-5 transition-all cursor-pointer group ${
                  dragOver
                    ? "border-violet-500 bg-violet-500/10"
                    : selectedFile
                    ? "border-emerald-500/50 bg-emerald-500/5"
                    : "border-slate-700 hover:border-slate-500 hover:bg-slate-800/50"
                }`}
                onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
                onDragLeave={() => setDragOver(false)}
                onDrop={handleDrop}
                onClick={() => fileRef.current?.click()}
              >
                <input
                  ref={fileRef}
                  type="file"
                  accept="audio/*,video/*"
                  className="hidden"
                  onChange={(e) => {
                    const f = e.target.files?.[0];
                    if (f) {
                      setSelectedFile(f);
                      if (!title) setTitle(f.name.replace(/\.[^/.]+$/, ""));
                    }
                  }}
                />
                {selectedFile ? (
                  <div>
                    <div className="w-12 h-12 mx-auto mb-3 rounded-full bg-emerald-500/20 flex items-center justify-center">
                      <svg className="w-6 h-6 text-emerald-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                      </svg>
                    </div>
                    <p className="text-white font-medium">{selectedFile.name}</p>
                    <p className="text-slate-500 text-sm mt-1">{(selectedFile.size / 1024 / 1024).toFixed(1)} MB</p>
                  </div>
                ) : (
                  <div>
                    <div className="w-12 h-12 mx-auto mb-3 rounded-full bg-slate-800 flex items-center justify-center group-hover:bg-slate-700 transition">
                      <svg className="w-6 h-6 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
                      </svg>
                    </div>
                    <p className="text-slate-300 font-medium">Drag and drop a file here</p>
                    <p className="text-slate-500 text-sm mt-1">or click to browse</p>
                    <p className="text-slate-600 text-xs mt-2">MP3, WAV, MP4, M4A, WEBM</p>
                  </div>
                )}
              </div>

            {/* Title */}
            <input
              type="text"
              placeholder="Title for the transcription"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              className="w-full bg-slate-800 border border-slate-700/50 rounded-xl px-4 py-3 text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-violet-500/50 focus:border-violet-500/50 mb-4"
            />

            {/* Advanced settings */}
            <details className="mb-5 group">
              <summary className="text-sm text-slate-500 cursor-pointer hover:text-slate-300 transition">
                Advanced settings
              </summary>
              <div className="mt-3 space-y-3">
                <div className="flex gap-3">
                  <input
                    type="number"
                    placeholder="Min speakers"
                    value={minSpeakers}
                    onChange={(e) => setMinSpeakers(e.target.value)}
                    className="flex-1 bg-slate-800 border border-slate-700/50 rounded-xl px-4 py-2.5 text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-violet-500/50"
                    min="1"
                  />
                  <input
                    type="number"
                    placeholder="Max speakers"
                    value={maxSpeakers}
                    onChange={(e) => setMaxSpeakers(e.target.value)}
                    className="flex-1 bg-slate-800 border border-slate-700/50 rounded-xl px-4 py-2.5 text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-violet-500/50"
                    min="1"
                  />
                </div>
                <textarea
                  placeholder="Vocabulary priming (domain-specific terms, names, abbreviations...)"
                  value={vocabulary}
                  onChange={(e) => setVocabulary(e.target.value)}
                  className="w-full bg-slate-800 border border-slate-700/50 rounded-xl px-4 py-2.5 text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-violet-500/50 text-sm resize-none"
                  rows={2}
                  maxLength={2000}
                />
                <p className="text-xs text-slate-600">
                  Add names, technical terms, or abbreviations to improve transcription accuracy.
                </p>
              </div>
            </details>

            {/* Error message */}
            {error && (
              <div className="mb-4 px-4 py-3 rounded-xl bg-red-500/10 border border-red-500/20 text-red-400 text-sm flex items-start gap-2">
                <svg className="w-4 h-4 mt-0.5 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4c-.77-.833-1.964-.833-2.732 0L3.34 16.5c-.77.833.192 2.5 1.732 2.5z" />
                </svg>
                <span>{error}</span>
              </div>
            )}

            {/* Actions */}
            <div className="flex justify-end gap-3">
              <button
                onClick={() => { setShowUpload(false); resetDialog(); }}
                className="px-5 py-2.5 text-slate-400 hover:text-white hover:bg-slate-800 rounded-xl transition"
              >
                Cancel
              </button>
              <button
                onClick={handleUpload}
                disabled={uploading || !selectedFile || !title.trim()}
                className="px-5 py-2.5 bg-gradient-to-r from-violet-600 to-indigo-600 text-white rounded-xl font-medium hover:from-violet-500 hover:to-indigo-500 disabled:opacity-40 disabled:cursor-not-allowed transition-all shadow-lg shadow-violet-500/25"
              >
                {uploading ? (
                  <span className="flex items-center gap-2">
                    <svg className="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                    </svg>
                    Uploading...
                  </span>
                ) : (
                  "Start transcription"
                )}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Search bar */}
      <div className="mb-6 relative">
        <div className="relative">
          <svg className="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
          </svg>
          <input
            type="text"
            placeholder="Search across all transcriptions..."
            value={searchQuery}
            onChange={(e) => handleSearchChange(e.target.value)}
            className="w-full bg-slate-900/50 border border-slate-800/50 rounded-xl pl-10 pr-4 py-2.5 text-white placeholder-slate-600 focus:outline-none focus:ring-2 focus:ring-violet-500/30 focus:border-violet-500/30 text-sm"
          />
          {searching && (
            <div className="absolute right-3.5 top-1/2 -translate-y-1/2 w-4 h-4 border border-violet-500/30 border-t-violet-500 rounded-full animate-spin" />
          )}
          {searchQuery && !searching && (
            <button
              onClick={() => { setSearchQuery(""); setSearchResults([]); }}
              className="absolute right-3.5 top-1/2 -translate-y-1/2 text-slate-500 hover:text-white transition"
            >
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          )}
        </div>

        {/* Search results */}
        {searchQuery && searchResults.length > 0 && (
          <div className="mt-3 space-y-3">
            <p className="text-xs text-slate-500">{searchResults.reduce((n, r) => n + r.segments.length, 0)} results in {searchResults.length} meeting(s)</p>
            {searchResults.map((result) => (
              <div key={result.meeting_id} className="bg-slate-900/50 border border-slate-800/50 rounded-xl overflow-hidden">
                <button
                  onClick={() => navigate(`/meetings/${result.meeting_id}`)}
                  className="w-full px-4 py-2.5 text-left hover:bg-slate-800/50 transition border-b border-slate-800/30"
                >
                  <span className="text-sm font-semibold text-violet-400">{result.meeting_title}</span>
                </button>
                <div className="divide-y divide-slate-800/30">
                  {result.segments.slice(0, 5).map((seg) => (
                    <button
                      key={seg.id}
                      onClick={() => navigate(`/meetings/${result.meeting_id}`)}
                      className="w-full px-4 py-2 text-left hover:bg-slate-800/30 transition flex items-start gap-3"
                    >
                      <span className="text-xs text-slate-600 font-mono mt-0.5 flex-shrink-0 w-10">
                        {Math.floor(seg.start_time / 60)}:{Math.floor(seg.start_time % 60).toString().padStart(2, "0")}
                      </span>
                      {seg.speaker_color && (
                        <span className="w-2 h-2 rounded-full mt-1.5 flex-shrink-0" style={{ backgroundColor: seg.speaker_color }} />
                      )}
                      <span className="text-sm text-slate-300 line-clamp-2">{seg.text}</span>
                    </button>
                  ))}
                  {result.segments.length > 5 && (
                    <div className="px-4 py-1.5 text-xs text-slate-600">
                      +{result.segments.length - 5} more matches
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
        {searchQuery && !searching && searchResults.length === 0 && (
          <p className="mt-3 text-sm text-slate-600">No results found</p>
        )}
      </div>

      {/* Error banner (for delete errors outside dialog) */}
      {error && !showUpload && (
        <div className="mb-4 px-4 py-3 rounded-xl bg-red-500/10 border border-red-500/20 text-red-400 text-sm flex items-center justify-between">
          <span>{error}</span>
          <button onClick={() => setError(null)} className="text-red-400 hover:text-red-300 ml-3">
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>
      )}

      {/* Meeting list */}
      {meetings.length === 0 ? (
        <div className="text-center py-24">
          <div className="w-20 h-20 mx-auto mb-6 rounded-2xl bg-slate-800/50 border border-slate-700/50 flex items-center justify-center">
            <svg className="w-10 h-10 text-slate-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4m-4-8a3 3 0 01-3-3V5a3 3 0 116 0v6a3 3 0 01-3 3z" />
            </svg>
          </div>
          <h3 className="text-xl font-semibold text-slate-300">No meetings yet</h3>
          <p className="text-slate-500 mt-2 max-w-sm mx-auto">
            Upload an audio or video file to start transcribing.
          </p>
        </div>
      ) : (
        <div className="space-y-3">
          {meetings.map((m) => {
            const badge = STATUS_LABELS[m.status] || { text: m.status, color: "bg-slate-800 text-slate-400", dot: "bg-slate-500" };
            return (
              <div
                key={m.id}
                className="group bg-slate-900/50 border border-slate-800/50 rounded-xl hover:border-slate-700/50 transition-all"
              >
                <div
                  onClick={() => navigate(`/meetings/${m.id}`)}
                  className="p-5 cursor-pointer hover:bg-slate-800/50 rounded-xl transition-all"
                >
                  <div className="flex items-center justify-between">
                    <div className="min-w-0 flex-1">
                      <h3 className="font-semibold text-white group-hover:text-violet-300 transition truncate flex items-center gap-2">
                        {m.title}
                      </h3>
                      <div className="flex items-center gap-3 mt-1.5 text-sm text-slate-500">
                        <span>{formatDate(m.created_at)}</span>
                        <span className="w-1 h-1 rounded-full bg-slate-700" />
                        <span>{formatDuration(m.duration)}</span>
                        {m.mode === "live" && (
                          <>
                            <span className="w-1 h-1 rounded-full bg-slate-700" />
                            <span className="text-red-400 text-xs font-medium">LIVE</span>
                          </>
                        )}
                        {m.speaker_count > 0 && (
                          <>
                            <span className="w-1 h-1 rounded-full bg-slate-700" />
                            <span>{m.speaker_count} speakers</span>
                          </>
                        )}
                        {m.segment_count > 0 && (
                          <>
                            <span className="w-1 h-1 rounded-full bg-slate-700" />
                            <span>{m.segment_count} segments</span>
                          </>
                        )}
                      </div>
                    </div>
                    <div className="flex items-center gap-3 ml-4">
                      <span className={`flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-medium ${badge.color}`}>
                        <span className={`w-1.5 h-1.5 rounded-full ${badge.dot}`} />
                        {badge.text}
                      </span>
                      <button
                        onClick={(e) => handleDelete(e, m.id)}
                        className="opacity-0 group-hover:opacity-100 text-slate-600 hover:text-red-400 transition-all p-1"
                        title="Delete"
                      >
                        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                        </svg>
                      </button>
                    </div>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </main>
  );
}
