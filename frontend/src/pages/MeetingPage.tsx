import { useEffect, useRef, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { getMeeting, startProcessing, getJobs, rediarizeMeeting, reidentifyMeeting, updateMeetingTitle } from "../api";
import { useStore } from "../store";
import type { ProgressUpdate } from "../types";
import TranscriptView from "../components/TranscriptView";
import SpeakerPanel from "../components/SpeakerPanel";
import AnalyticsPanel from "../components/AnalyticsPanel";
import AudioPlayer from "../components/AudioPlayer";
import ProgressTracker from "../components/ProgressTracker";
import ExportDialog from "../components/ExportDialog";
import DuplicateReprocessDialog from "../components/DuplicateReprocessDialog";

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
  const [skipLlm, setSkipLlm] = useState(false);
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

  async function handleProcess() {
    if (!id) return;
    await startProcessing(id, skipLlm);
    setProgress({ type: "progress", progress: 0, step: "Starting...", status: "processing" });
    loadMeeting();
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
        <div className="text-center py-20">
          <div className="w-20 h-20 mx-auto mb-6 rounded-2xl bg-slate-800/50 border border-slate-700/50 flex items-center justify-center">
            <svg className="w-10 h-10 text-slate-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z" />
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
          </div>
          <h3 className="text-xl font-semibold text-slate-300">Ready to transcribe</h3>
          <p className="text-slate-500 mt-2">Click "Start transcription" to begin processing</p>
          <label className="mt-5 inline-flex items-center gap-2.5 cursor-pointer select-none group">
            <div className="relative">
              <input
                type="checkbox"
                className="sr-only peer"
                checked={!skipLlm}
                onChange={(e) => setSkipLlm(!e.target.checked)}
              />
              <div className="w-9 h-5 bg-slate-700 peer-checked:bg-violet-600 rounded-full transition-colors" />
              <div className="absolute top-0.5 left-0.5 w-4 h-4 bg-white rounded-full shadow transition-transform peer-checked:translate-x-4" />
            </div>
            <span className="text-sm text-slate-400 group-hover:text-slate-300 transition-colors">
              AI analysis (speaker identification &amp; intro detection)
            </span>
          </label>
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
