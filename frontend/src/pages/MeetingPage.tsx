import { useEffect, useRef, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { getMeeting, startProcessing, getJobs, rediarizeMeeting, reidentifyMeeting, updateMeetingTitle, updateMeeting } from "../api";
import { useStore } from "../store";
import type { ProgressUpdate } from "../types";
import TranscriptView from "../components/TranscriptView";
import SpeakerPanel from "../components/SpeakerPanel";
import AnalyticsPanel from "../components/AnalyticsPanel";
import AudioPlayer from "../components/AudioPlayer";
import ProgressTracker from "../components/ProgressTracker";
import ExportDialog from "../components/ExportDialog";
import DuplicateReprocessDialog from "../components/DuplicateReprocessDialog";
import { parseVocabulary, formatVocabulary, cleanParticipants } from "../utils/vocabulary";

export default function MeetingPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const {
    currentMeeting, setCurrentMeeting,
    progress, setProgress,
  } = useStore();
  const [showExport, setShowExport] = useState(false);
  const [showReprocess, setShowReprocess] = useState(false);
  const [showDuplicate, setShowDuplicate] = useState(false);
  const [participants, setParticipants] = useState("");
  const [domainVocab, setDomainVocab] = useState("");
  const [showAdvancedVocab, setShowAdvancedVocab] = useState(false);
  const [isSavingVocab, setIsSavingVocab] = useState(false);
  const [sidebarTab, setSidebarTab] = useState<"speakers" | "analytics">("speakers");
  const [editingTitle, setEditingTitle] = useState(false);
  const [titleValue, setTitleValue] = useState("");
  const wsRef = useRef<WebSocket | null>(null);
  const audioRef = useRef<HTMLAudioElement>(null);
  const titleInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!id) return;
    loadMeeting();

    return () => {
      wsRef.current?.close();
      setCurrentMeeting(null);
      setProgress(null);
    };
  }, [id]);

  useEffect(() => {
    if (!id) return;
    connectWebSocket();
    return () => {
      wsRef.current?.close();
    };
  }, [id]);

  async function loadMeeting() {
    if (!id) return;
    const m = await getMeeting(id);
    setCurrentMeeting(m);
    if (m.status === "processing") {
      const jobs = await getJobs(id);
      const active = jobs.find((j) => j.status === "running" || j.status === "pending");
      if (active) {
        setProgress({ type: "progress", progress: active.progress, step: active.current_step || "Processing...", status: "processing" });
      }
    }
    if (m.status === "finalizing") {
      const jobs = await getJobs(id);
      const active = jobs.find((j) => j.status === "running" || j.status === "pending");
      if (active) {
        setProgress({ type: "progress", progress: active.progress, step: active.current_step || "Finalizing...", status: "finalizing" });
      }
    }
  }

  function connectWebSocket() {
    if (!id) return;
    const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
    const ws = new WebSocket(`${proto}//${window.location.host}/ws/meetings/${id}`);
    wsRef.current = ws;
    ws.onmessage = (event) => {
      const data: ProgressUpdate = JSON.parse(event.data);
      if (data.type === "ping") return;
      setProgress(data);
      if (data.type === "progress" && data.progress === 100) {
        setTimeout(() => loadMeeting(), 500);
      }
      if (data.type === "error") {
        setTimeout(() => loadMeeting(), 500);
      }
    };
    ws.onclose = (event) => {
      if (event.code === 4004) return; // meeting deleted/not found — stop reconnecting
      setTimeout(() => {
        if (document.visibilityState === "visible") connectWebSocket();
      }, 3000);
    };
  }

  useEffect(() => {
    if (currentMeeting?.vocabulary) {
      const parsed = parseVocabulary(currentMeeting.vocabulary);
      setDomainVocab(parsed.vocabulary);
    } else {
      setDomainVocab("");
    }
    if (currentMeeting?.participants) {
      setParticipants(currentMeeting.participants);
    } else {
      setParticipants("");
    }
  }, [currentMeeting?.id]);

  async function handleProcess() {
    if (!id || !currentMeeting) return;
    const formatted = formatVocabulary(cleanParticipants(participants), domainVocab);
    const cleanedParticipants = cleanParticipants(participants).join(", ");
    const updates: { vocabulary?: string | null; participants?: string | null } = {};
    if (formatted !== (currentMeeting.vocabulary || "")) {
      updates.vocabulary = formatted;
    }
    if (cleanedParticipants !== (currentMeeting.participants || "")) {
      updates.participants = cleanedParticipants;
    }
    if (Object.keys(updates).length > 0) {
      try {
        await updateMeeting(id, updates);
      } catch (err) {
        console.error("Failed to update vocabulary before processing:", err);
      }
    }
    await startProcessing(id);
    setProgress({ type: "progress", progress: 0, step: "Starting...", status: "processing" });
    loadMeeting();
  }

  async function handleSaveVocabulary() {
    if (!id || !currentMeeting) return;
    setIsSavingVocab(true);
    try {
      const formatted = formatVocabulary(cleanParticipants(participants), domainVocab);
      const cleanedParticipants = cleanParticipants(participants).join(", ");
      const updated = await updateMeeting(id, { vocabulary: formatted, participants: cleanedParticipants });
      setCurrentMeeting({ ...currentMeeting, vocabulary: updated.vocabulary, participants: updated.participants });
    } catch (err) {
      console.error("Failed to save vocabulary:", err);
    } finally {
      setIsSavingVocab(false);
    }
  }

  async function handleRediarize() {
    if (!id) return;
    setShowReprocess(false);
    await rediarizeMeeting(id);
    setProgress({ type: "progress", progress: 0, step: "Re-diarizing...", status: "processing" });
    loadMeeting();
  }

  function startTitleEdit() {
    if (!currentMeeting) return;
    setTitleValue(currentMeeting.title);
    setEditingTitle(true);
    setTimeout(() => titleInputRef.current?.select(), 0);
  }

  async function commitTitleEdit() {
    setEditingTitle(false);
    const newTitle = titleValue.trim();
    if (!id || !currentMeeting || !newTitle || newTitle === currentMeeting.title) return;
    const updated = await updateMeetingTitle(id, newTitle);
    setCurrentMeeting({ ...currentMeeting, title: updated.title });
  }

  async function handleReidentify() {
    if (!id) return;
    setShowReprocess(false);
    await reidentifyMeeting(id);
    setProgress({ type: "progress", progress: 0, step: "Re-identifying...", status: "processing" });
    loadMeeting();
  }

  if (!currentMeeting) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="w-10 h-10 border-2 border-violet-500/30 border-t-violet-500 rounded-full animate-spin" />
      </div>
    );
  }

  const isProcessing = currentMeeting.status === "processing";
  const isCompleted = currentMeeting.status === "completed";
  const isUploaded = currentMeeting.status === "uploaded";
  const isFailed = currentMeeting.status === "failed";
  const isFinalizing = currentMeeting.status === "finalizing";

  const currentVocabStr = (currentMeeting.vocabulary || "").trim();
  const newVocabStr = (formatVocabulary(cleanParticipants(participants), domainVocab) || "").trim();
  const hasVocabChanges = newVocabStr !== currentVocabStr;

  return (
    <main className="max-w-7xl mx-auto px-6 py-6">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-4">
          <button
            onClick={() => navigate("/")}
            className="w-8 h-8 rounded-lg bg-slate-800 hover:bg-slate-700 flex items-center justify-center text-slate-400 hover:text-white transition"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
            </svg>
          </button>
          <div>
            {editingTitle ? (
              <input
                ref={titleInputRef}
                type="text"
                value={titleValue}
                onChange={(e) => setTitleValue(e.target.value)}
                onBlur={commitTitleEdit}
                onKeyDown={(e) => {
                  if (e.key === "Enter") { e.preventDefault(); commitTitleEdit(); }
                  if (e.key === "Escape") { e.preventDefault(); setEditingTitle(false); }
                }}
                maxLength={500}
                className="text-xl font-bold text-white bg-slate-800 border border-violet-500/50 rounded-lg px-2 py-0.5 focus:outline-none focus:ring-2 focus:ring-violet-500/50"
              />
            ) : (
              <h1
                onDoubleClick={startTitleEdit}
                title="Double-click to rename"
                className="text-xl font-bold text-white cursor-text"
              >
                {currentMeeting.title}
              </h1>
            )}
            <p className="text-sm text-slate-500 mt-0.5">
              {currentMeeting.duration ? (
                <>
                  {Math.floor(currentMeeting.duration / 60)}:{Math.floor(currentMeeting.duration % 60).toString().padStart(2, "0")} min
                  {currentMeeting.speaker_count > 0 && ` \u00B7 ${currentMeeting.speaker_count} speakers`}
                </>
              ) : null}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          {isUploaded && (
            <button
              onClick={handleProcess}
              className="px-5 py-2.5 bg-gradient-to-r from-violet-600 to-indigo-600 text-white rounded-xl font-medium hover:from-violet-500 hover:to-indigo-500 transition-all shadow-lg shadow-violet-500/25"
            >
              <span className="flex items-center gap-2">
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z" />
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
                Start transcription
              </span>
            </button>
          )}
          {isFailed && (
            <button
              onClick={handleProcess}
              className="px-5 py-2.5 bg-gradient-to-r from-amber-600 to-orange-600 text-white rounded-xl font-medium hover:from-amber-500 hover:to-orange-500 transition-all shadow-lg shadow-amber-500/25"
            >
              Retry
            </button>
          )}
          {isCompleted && (
            <>
              {/* Reprocess dropdown */}
              <div className="relative">
                <button
                  onClick={() => setShowReprocess(!showReprocess)}
                  className="px-4 py-2.5 bg-slate-800 text-slate-400 border border-slate-700/50 rounded-xl font-medium hover:text-white hover:border-slate-600 transition-all"
                  title="Reprocess options"
                >
                  <span className="flex items-center gap-2">
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                    </svg>
                    Reprocess
                  </span>
                </button>
                {showReprocess && (
                  <>
                  <div className="fixed inset-0 z-10" onClick={() => setShowReprocess(false)} />
                  <div className="absolute right-0 top-full mt-1 bg-slate-800 border border-slate-700 rounded-xl shadow-xl py-1 z-20 min-w-[220px]">
                    <button
                      onClick={handleRediarize}
                      className="w-full text-left px-4 py-2.5 hover:bg-slate-700 transition"
                    >
                      <div className="text-sm text-white font-medium">Re-diarize</div>
                      <div className="text-xs text-slate-500 mt-0.5">Re-assign speakers without re-transcribing</div>
                    </button>
                    <button
                      onClick={handleReidentify}
                      className="w-full text-left px-4 py-2.5 hover:bg-slate-700 transition"
                    >
                      <div className="text-sm text-white font-medium">Re-identify speakers</div>
                      <div className="text-xs text-slate-500 mt-0.5">Re-run AI speaker naming only</div>
                    </button>
                    <div className="border-t border-slate-700 my-1" />
                    <button
                      onClick={handleProcess}
                      className="w-full text-left px-4 py-2.5 hover:bg-slate-700 transition"
                    >
                      <div className="text-sm text-white font-medium">Full reprocess</div>
                      <div className="text-xs text-slate-500 mt-0.5">Re-transcribe and re-diarize everything</div>
                    </button>
                    <button
                      onClick={() => { setShowReprocess(false); setShowDuplicate(true); }}
                      className="w-full text-left px-4 py-2.5 hover:bg-slate-700 transition"
                    >
                      <div className="text-sm text-white font-medium">Duplicate &amp; reprocess…</div>
                      <div className="text-xs text-slate-500 mt-0.5">Copy this meeting and try another backend</div>
                    </button>
                  </div>
                  </>
                )}
              </div>
              <button
                onClick={() => setShowExport(true)}
                className="px-5 py-2.5 bg-gradient-to-r from-emerald-600 to-teal-600 text-white rounded-xl font-medium hover:from-emerald-500 hover:to-teal-500 disabled:opacity-40 disabled:cursor-not-allowed transition-all shadow-lg shadow-emerald-500/25"
              >
                <span className="flex items-center gap-2">
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
                  </svg>
                  Export
                </span>
              </button>
            </>
          )}
        </div>
      </div>

      {/* Progress (processing or finalizing) */}
      {(isProcessing || isFinalizing) && progress && (
        <ProgressTracker progress={progress} />
      )}

      {/* Failed state */}
      {isFailed && (
        <div className="rounded-xl bg-red-500/10 border border-red-500/20 p-5 mb-6">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-lg bg-red-500/20 flex items-center justify-center flex-shrink-0">
              <svg className="w-5 h-5 text-red-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4c-.77-.833-1.732-.833-2.464 0L4.34 16.5c-.77.833.192 2.5 1.732 2.5z" />
              </svg>
            </div>
            <div>
              <p className="font-medium text-red-400">Processing failed</p>
              {progress?.error && <p className="text-red-400/70 text-sm mt-0.5">{progress.error}</p>}
            </div>
          </div>
        </div>
      )}

      {/* Completed: show transcript */}
      {isCompleted && currentMeeting.segments && (
        <>
          <AudioPlayer meetingId={currentMeeting.id} audioRef={audioRef} />
          <div className="flex gap-6 mt-5">
            <div className="flex-1 min-w-0">
              <TranscriptView
                segments={currentMeeting.segments}
                speakers={currentMeeting.speakers || []}
                audioRef={audioRef}
                onUpdate={loadMeeting}
              />
            </div>
            <div className="w-72 flex-shrink-0">
              {/* Sidebar tab toggle */}
              <div className="flex rounded-lg bg-slate-800/50 p-0.5 mb-3">
                {(["speakers", "analytics"] as const).map((tab) => (
                  <button
                    key={tab}
                    onClick={() => setSidebarTab(tab)}
                    className={`flex-1 text-[10px] font-medium py-1.5 rounded-md transition ${
                      sidebarTab === tab
                        ? "bg-slate-700 text-white shadow-sm"
                        : "text-slate-500 hover:text-slate-300"
                    }`}
                  >
                    {tab === "speakers" ? "Speakers" : "Stats"}
                  </button>
                ))}
              </div>
              {sidebarTab === "speakers" ? (
                <SpeakerPanel
                  speakers={currentMeeting.speakers || []}
                  segments={currentMeeting.segments}
                  onUpdate={loadMeeting}
                  meetingId={currentMeeting.id}
                  participants={cleanParticipants(currentMeeting.participants || "")}
                />
              ) : (
                <AnalyticsPanel meetingId={currentMeeting.id} />
              )}
            </div>
          </div>
        </>
      )}

      {/* Uploaded but not started */}
      {isUploaded && (
        <div className="max-w-xl mx-auto py-12">
          <div className="bg-slate-900/80 border border-slate-800 rounded-2xl p-8 shadow-xl text-center">
            <div className="w-16 h-16 mx-auto mb-5 rounded-2xl bg-violet-500/10 border border-violet-500/20 flex items-center justify-center">
              <svg className="w-8 h-8 text-violet-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0zm6 3a2 2 0 11-4 0 2 2 0 014 0zM7 10a2 2 0 11-4 0 2 2 0 014 0z" />
              </svg>
            </div>
            <h3 className="text-xl font-bold text-white">Ready to transcribe</h3>
            <p className="text-slate-400 text-sm mt-1.5 max-w-md mx-auto">
              Provide names of known speakers and domain terminology to prime the Transcriber with accurate vocabulary.
            </p>

            <div className="mt-6 text-left">
              <label className="block text-xs font-semibold text-slate-300 uppercase tracking-wider mb-2">
                Meeting Participants
              </label>
              <textarea
                value={participants}
                onChange={(e) => setParticipants(e.target.value)}
                placeholder="Paste names from Google Meet, Zoom, Teams, or call chat"
                className="w-full bg-slate-800 border border-slate-700/50 rounded-xl px-4 py-2 text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-violet-500/50 text-sm resize-none"
                rows={3}
                maxLength={2000}
              />
              <p className="text-xs text-slate-500 mt-2">
                Names are cleaned automatically (emails, timestamps, status markers stripped).
              </p>
            </div>

            <div className="mt-4 text-left">
              <details className="group" open={Boolean(domainVocab) || showAdvancedVocab} onToggle={(e) => setShowAdvancedVocab((e.target as HTMLDetailsElement).open)}>
                <summary className="text-xs font-semibold text-slate-400 cursor-pointer hover:text-slate-300 transition uppercase tracking-wider">
                  Additional vocabulary &amp; domain terms
                </summary>
                <div className="mt-2 space-y-1.5">
                  <textarea
                    placeholder="Domain-specific terms, technical jargon, acronyms..."
                    value={domainVocab}
                    onChange={(e) => setDomainVocab(e.target.value)}
                    className="w-full bg-slate-800 border border-slate-700/50 rounded-xl px-4 py-2 text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-violet-500/50 text-sm resize-none"
                    rows={2}
                    maxLength={2000}
                  />
                  <p className="text-xs text-slate-500">
                    Additional technical terms or jargon to help the Transcriber spell them correctly.
                  </p>
                </div>
              </details>
            </div>

            <div className="mt-8 flex items-center justify-between pt-6 border-t border-slate-800/80">
              <div className="flex items-center gap-3">
                {hasVocabChanges ? (
                  <button
                    type="button"
                    onClick={handleSaveVocabulary}
                    disabled={isSavingVocab}
                    className="text-xs text-violet-400 hover:text-violet-300 font-medium transition flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-violet-500/10 hover:bg-violet-500/20 border border-violet-500/30 disabled:opacity-50"
                  >
                    {isSavingVocab ? "Saving..." : "Save changes"}
                  </button>
                ) : (
                  <span className="text-xs text-slate-500">
                    {cleanParticipants(participants).length > 0
                      ? `${cleanParticipants(participants).length} participant${cleanParticipants(participants).length > 1 ? "s" : ""} configured`
                      : "No participants configured"}
                  </span>
                )}
              </div>

              <button
                type="button"
                onClick={handleProcess}
                className="px-6 py-2.5 bg-gradient-to-r from-violet-600 to-indigo-600 text-white rounded-xl font-medium hover:from-violet-500 hover:to-indigo-500 transition-all shadow-lg shadow-violet-500/25 flex items-center gap-2"
              >
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z" />
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
                <span>Start transcription</span>
              </button>
            </div>
          </div>
        </div>
      )}

      {showExport && (
        <ExportDialog meetingId={currentMeeting.id} onClose={() => setShowExport(false)} />
      )}

      {showDuplicate && (
        <DuplicateReprocessDialog
          meetingId={currentMeeting.id}
          currentPresetId={currentMeeting.preset_id}
          onClose={() => setShowDuplicate(false)}
          onCreated={(newId) => { setShowDuplicate(false); navigate(`/meetings/${newId}`); }}
        />
      )}
    </main>
  );
}
