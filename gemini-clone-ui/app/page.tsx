"use client";

import React, { useState, useRef } from "react";

// ── Types ────────────────────────────────────────────────────────────────────
interface PipelineStep {
  id: number;
  label: string;
  status: "waiting" | "running" | "done" | "error";
  detail?: string;
}

interface HistoryItem {
  id: string;
  prompt: string;
  size: string;
  canvasW: number;
  canvasH: number;
  fileName?: string;
  imageB64: string;
}

const INITIAL_STEPS: PipelineStep[] = [
  { id: 1, label: "Parsing prompt & extracting brand data",          status: "waiting" },
  { id: 2, label: "Building cinematic scene prompt",                 status: "waiting" },
  { id: 3, label: "Generating background image with AI model",       status: "waiting" },
  { id: 4, label: "Rendering graphic — compositing text & branding", status: "waiting" },
  { id: 5, label: "Encoding final PNG for delivery",                 status: "waiting" },
];

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const SIZE_OPTIONS = [
  { value: "square", label: "Square",  sub: "1080 × 1080", icon: "▪" },
  { value: "story",  label: "Story",   sub: "1080 × 1920", icon: "▮" },
  { value: "og",     label: "OG Card", sub: "1200 × 630",  icon: "▬" },
] as const;
type Size = typeof SIZE_OPTIONS[number]["value"];

// ── Octopus SVG logo ─────────────────────────────────────────────────────────
const OctopusLogo = ({ size = 56 }: { size?: number }) => (
  <svg width={size} height={size} viewBox="0 0 100 100" fill="none" xmlns="http://www.w3.org/2000/svg">
    <ellipse cx="50" cy="42" rx="24" ry="26" fill="url(#octoGrad)" />
    <ellipse cx="50" cy="30" rx="20" ry="16" fill="url(#octoGrad2)" />
    <circle cx="43" cy="28" r="4" fill="white" /><circle cx="57" cy="28" r="4" fill="white" />
    <circle cx="44" cy="29" r="2" fill="#0f0f1a" /><circle cx="58" cy="29" r="2" fill="#0f0f1a" />
    <circle cx="44.5" cy="28.5" r="0.8" fill="white" /><circle cx="58.5" cy="28.5" r="0.8" fill="white" />
    <path d="M30 58 Q22 65 26 75 Q28 80 24 85" stroke="#421d60"strokeWidth="3.5" strokeLinecap="round" fill="none"/>
    <path d="M36 63 Q30 72 33 82 Q34 87 30 92" stroke="#421d60" strokeWidth="3.5" strokeLinecap="round" fill="none"/>
    <path d="M44 66 Q42 76 45 85 Q46 90 43 95" stroke="#421d60" strokeWidth="3.5" strokeLinecap="round" fill="none"/>
    <path d="M56 66 Q58 76 55 85 Q54 90 57 95" stroke="#421d60" strokeWidth="3.5" strokeLinecap="round" fill="none"/>
    <path d="M64 63 Q70 72 67 82 Q66 87 70 92" stroke="#421d60" strokeWidth="3.5" strokeLinecap="round" fill="none"/>
    <path d="M70 58 Q78 65 74 75 Q72 80 76 85" stroke="#421d60" strokeWidth="3.5" strokeLinecap="round" fill="none"/>
    <circle cx="24.5" cy="70" r="2" fill="#421d60" opacity="0.7"/>
    <circle cx="31.5" cy="73" r="2" fill="#421d60" opacity="0.7"/>
    <circle cx="44"   cy="76" r="2" fill="#421d60" opacity="0.7"/>
    <circle cx="56"   cy="76" r="2" fill="#421d60" opacity="0.7"/>
    <circle cx="68.5" cy="73" r="2" fill="#421d60" opacity="0.7"/>
    <circle cx="75.5" cy="70" r="2" fill="#421d60" opacity="0.7"/>
    <defs>
      <radialGradient id="octoGrad" cx="40%" cy="35%" r="65%">
        <stop offset="0%" stopColor="#421d60"/><stop offset="100%" stopColor="#5b21b6"/>
      </radialGradient>
      <radialGradient id="octoGrad2" cx="40%" cy="30%" r="65%">
        <stop offset="0%" stopColor="#c4b5fd"/><stop offset="100%" stopColor="#421d60"/>
      </radialGradient>
    </defs>
  </svg>
);

// ── Step icon ─────────────────────────────────────────────────────────────────
const StepIcon = ({ status }: { status: PipelineStep["status"] }) => {
  if (status === "done") return (
    <span className="flex items-center justify-center w-6 h-6 rounded-full bg-emerald-500/20 border border-emerald-500/50">
      <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
        <path d="M2 6l3 3 5-5" stroke="#34d399" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"/>
      </svg>
    </span>
  );
  if (status === "running") return (
    <span className="flex items-center justify-center w-6 h-6 rounded-full border border-violet-400/60 bg-violet-500/10">
      <span className="w-3 h-3 border-2 border-violet-400 border-t-transparent rounded-full animate-spin block" />
    </span>
  );
  if (status === "error") return (
    <span className="flex items-center justify-center w-6 h-6 rounded-full bg-red-500/20 border border-red-500/50">
      <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
        <path d="M3 3l6 6M9 3l-6 6" stroke="#f87171" strokeWidth="1.8" strokeLinecap="round"/>
      </svg>
    </span>
  );
  return (
    <span className="flex items-center justify-center w-6 h-6 rounded-full border border-[#32323d] bg-[#17171c]">
      <span className="w-1.5 h-1.5 rounded-full bg-[#42424f] block" />
    </span>
  );
};

// ── File type badge ───────────────────────────────────────────────────────────
const FileTypeTag = ({ name }: { name: string }) => {
  const ext = name.split(".").pop()?.toUpperCase() ?? "FILE";
  const colors: Record<string, string> = {
    PDF:  "bg-red-900/40 text-red-300 border-red-800/40",
    TXT:  "bg-blue-900/40 text-blue-300 border-blue-800/40",
    DOCX: "bg-sky-900/40 text-sky-300 border-sky-800/40",
    PNG:  "bg-green-900/40 text-green-300 border-green-800/40",
    JPG:  "bg-yellow-900/40 text-yellow-300 border-yellow-800/40",
    SVG:  "bg-purple-900/40 text-purple-300 border-purple-800/40",
    WEBP: "bg-teal-900/40 text-teal-300 border-teal-800/40",
  };
  return (
    <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded border ${colors[ext] ?? "bg-violet-900/40 text-violet-300 border-violet-800/40"}`}>
      {ext}
    </span>
  );
};

// ── Logo preview thumbnail ────────────────────────────────────────────────────
const LogoPreview = ({ file, onRemove }: { file: File; onRemove: () => void }) => {
  const [url] = React.useState(() => URL.createObjectURL(file));
  React.useEffect(() => () => URL.revokeObjectURL(url), [url]);
  return (
    <div className="flex items-center gap-3 bg-[#0b0b14] border border-[#2a2a38] rounded-xl p-3">
      <div className="w-14 h-10 rounded-lg bg-[#17171c] border border-[#2a2a38] flex items-center justify-center overflow-hidden flex-shrink-0">
        <img src={url} alt="Logo preview" className="max-w-full max-h-full object-contain" />
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <FileTypeTag name={file.name} />
          <span className="text-xs text-white font-medium truncate">{file.name}</span>
        </div>
        <p className="text-[10px] text-[#555] mt-0.5">{(file.size / 1024).toFixed(0)} KB · Will be placed top-left of post</p>
      </div>
      <button
        onClick={onRemove}
        className="text-[#555] hover:text-red-400 transition text-lg leading-none flex-shrink-0 px-1"
        title="Remove logo"
      >×</button>
    </div>
  );
};

// ── Main component ────────────────────────────────────────────────────────────
export default function OctopusImageWorkspace() {
  const [prompt, setPrompt]             = useState("");
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [logoFile, setLogoFile]         = useState<File | null>(null);   // ← NEW
  const [size, setSize]                 = useState<Size>("square");
  const [loading, setLoading]           = useState(false);
  const [steps, setSteps]               = useState<PipelineStep[]>(INITIAL_STEPS);
  const [pipelineVisible, setPipelineVisible] = useState(false);
  const [history, setHistory]           = useState<HistoryItem[]>([]);
  const [errorMsg, setErrorMsg]         = useState<string | null>(null);

  const fileInputRef = useRef<HTMLInputElement>(null);
  const logoInputRef = useRef<HTMLInputElement>(null);   // ← NEW

  const handleDragOver = (e: React.DragEvent) => e.preventDefault();
  const handleDrop     = (e: React.DragEvent) => {
    e.preventDefault();
    const f = e.dataTransfer.files[0];
    if (f) setSelectedFile(f);
  };

  // Validate logo file type client-side before upload
  const handleLogoChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0];
    if (!f) return;
    const allowed = ["image/png", "image/jpeg", "image/webp", "image/svg+xml"];
    if (!allowed.includes(f.type)) {
      alert("Logo must be PNG, JPG, WEBP, or SVG. PNG with transparent background works best.");
      return;
    }
    if (f.size > 2 * 1024 * 1024) {
      alert("Logo file must be under 2 MB.");
      return;
    }
    setLogoFile(f);
    // Reset input so the same file can be re-selected after removal
    e.target.value = "";
  };

  const updateStep = (id: number, patch: Partial<PipelineStep>) =>
    setSteps(prev => prev.map(s => s.id === id ? { ...s, ...patch } : s));

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!prompt.trim() && !selectedFile) return;

    setLoading(true);
    setErrorMsg(null);
    setPipelineVisible(true);
    setSteps(INITIAL_STEPS.map(s => ({ ...s, status: "waiting", detail: undefined })));

    const savedPrompt   = prompt;
    const savedFileName = selectedFile?.name;

    const formData = new FormData();
    if (prompt.trim())  formData.append("prompt", prompt);
    if (selectedFile)   formData.append("file",   selectedFile);
    if (logoFile)       formData.append("logo",   logoFile);    // ← NEW
    formData.append("size", size);

    setPrompt("");
    setSelectedFile(null);
    // Note: we keep logoFile set so the user doesn't have to re-upload on next generation

    try {
      const response = await fetch(`${API_BASE}/api/generate-stream`, {
        method: "POST",
        body:   formData,
      });

      if (!response.ok) {
        const body = await response.json().catch(() => ({ detail: response.statusText }));
        throw new Error(body.detail ?? `HTTP ${response.status}`);
      }
      if (!response.body) throw new Error("No response body from server.");

      const reader  = response.body.getReader();
      const decoder = new TextDecoder();
      let   buffer  = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const blocks = buffer.split("\n\n");
        buffer = blocks.pop() ?? "";

        for (const block of blocks) {
          const lines     = block.split("\n");
          const eventLine = lines.find(l => l.startsWith("event:"));
          const dataLine  = lines.find(l => l.startsWith("data:"));
          if (!eventLine || !dataLine) continue;
          const event = eventLine.replace("event:", "").trim();
          let   data: Record<string, unknown>;
          try { data = JSON.parse(dataLine.replace("data:", "").trim()); }
          catch { continue; }

          if (event === "step") {
            updateStep(data.id as number, {
              label:  data.label  as string,
              status: data.status as PipelineStep["status"],
              detail: data.detail as string | undefined,
            });
          } else if (event === "complete") {
            setHistory(prev => [{
              id:       Date.now().toString(),
              prompt:   savedPrompt || "Extracted from document.",
              size:     data.size    as string,
              canvasW:  data.canvas_w as number,
              canvasH:  data.canvas_h as number,
              fileName: savedFileName,
              imageB64: data.image_b64 as string,
            }, ...prev]);
          } else if (event === "error") {
            setErrorMsg(data.message as string);
            setSteps(prev => prev.map(s => s.status === "running" ? { ...s, status: "error" } : s));
          }
        }
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Unknown error";
      setErrorMsg(msg);
      setSteps(prev => prev.map(s => s.status === "running" ? { ...s, status: "error" } : s));
    } finally {
      setLoading(false);
    }
  };

  const hasInput = prompt.trim() || selectedFile;
  const allDone  = steps.every(s => s.status === "done");
  const hasError = steps.some(s => s.status === "error");

  return (
    <div className="min-h-screen bg-[#080810] text-[#e3e3e3] font-sans flex flex-col">

      {/* Ambient blobs */}
      <div className="fixed inset-0 pointer-events-none overflow-hidden">
        <div className="absolute top-[-20%] left-[10%]  w-[500px] h-[500px] rounded-full bg-violet-700/8 blur-[120px]" />
        <div className="absolute bottom-[-10%] right-[5%] w-[400px] h-[400px] rounded-full bg-blue-700/8  blur-[100px]" />
        <div className="absolute top-[40%] left-[50%]   w-[300px] h-[300px] rounded-full bg-violet-900/6 blur-[80px]"  />
      </div>

      {/* Navbar */}
      <header className="relative z-10 border-b border-white/5 px-8 py-4 flex justify-between items-center bg-[#0a0a12]/80 backdrop-blur-md">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg bg-violet-600/20 border border-violet-500/30 flex items-center justify-center text-base">🐙</div>
          <span className="text-sm font-semibold text-white tracking-wide">Octopus AI</span>
          <span className="text-[10px] text-[#555] mx-1">|</span>
          <span className="text-xs text-[#666]">Image Studio</span>
        </div>
        <span className="text-[10px] bg-emerald-950/60 text-emerald-400 px-3 py-1 rounded-full border border-emerald-900/40 font-medium">
          ● Engine Connected
        </span>
      </header>

      {/* Hero */}
      <div className="relative z-10 flex flex-col items-center justify-center pt-16 pb-10 px-4 text-center">
        <div className="mb-6 relative">
          <div className="absolute inset-0 scale-150 rounded-full bg-violet-600/10 blur-2xl" />
          <OctopusLogo size={72} />
        </div>
        <h1 className="text-4xl md:text-5xl font-bold text-white mb-3 tracking-tight">
          Create your image with{" "}
          <span className="bg-gradient-to-r from-violet-400 to-blue-400 bg-clip-text text-transparent">Octopus</span>
        </h1>
        <p className="text-sm text-[#666] max-w-md">
          Describe your marketing vision or upload a brief — AI generates a premium commercial poster in seconds.
        </p>
      </div>

      {/* Main */}
      <main className="relative z-10 flex-1 max-w-5xl w-full mx-auto px-4 pb-12 flex flex-col gap-6">

        {/* ── Input card ── */}
        <div className="bg-[#0e0e18]/90 border border-white/6 rounded-2xl p-6 backdrop-blur-md shadow-2xl">

          {/* Brief upload zone */}
          <div
            onDragOver={handleDragOver}
            onDrop={handleDrop}
            onClick={() => fileInputRef.current?.click()}
            className={`relative border-2 border-dashed rounded-xl p-5 mb-4 cursor-pointer transition-all duration-200 text-center group
              ${selectedFile
                ? "border-violet-500/70 bg-violet-950/20"
                : "border-[#2a2a38] hover:border-violet-500/40 bg-[#0b0b14] hover:bg-violet-950/10"}`}
          >
            <input
              type="file"
              ref={fileInputRef}
              className="hidden"
              onChange={e => e.target.files?.[0] && setSelectedFile(e.target.files[0])}
            />
            {selectedFile ? (
              <div className="flex items-center justify-center gap-3">
                <FileTypeTag name={selectedFile.name} />
                <span className="text-sm text-white font-medium truncate max-w-xs">{selectedFile.name}</span>
                <button
                  onClick={ev => { ev.stopPropagation(); setSelectedFile(null); }}
                  className="ml-2 text-[#555] hover:text-red-400 transition text-lg leading-none"
                >×</button>
              </div>
            ) : (
              <div className="space-y-1.5">
                <div className="text-2xl mb-1">📎</div>
                <p className="text-sm font-medium text-[#ccc] group-hover:text-white transition">
                  Drop your brief here or <span className="text-violet-400">browse files</span>
                </p>
                <p className="text-[11px] text-[#555]">PDF · TXT · DOCX · PNG · JPG — max 10 MB</p>
              </div>
            )}
          </div>

          {/* ── Logo upload section (NEW) ── */}
          <div className="mb-4">
            <div className="flex items-center justify-between mb-2">
              <label className="text-xs font-semibold text-[#9ea1a4] uppercase tracking-widest">
                Brand Logo
                <span className="ml-2 text-[10px] font-normal normal-case text-[#555]">optional</span>
              </label>
              {logoFile && (
                <button
                  onClick={() => setLogoFile(null)}
                  className="text-[10px] text-[#555] hover:text-red-400 transition"
                >
                  Remove logo
                </button>
              )}
            </div>

            {logoFile ? (
              <LogoPreview file={logoFile} onRemove={() => setLogoFile(null)} />
            ) : (
              <button
                onClick={() => logoInputRef.current?.click()}
                className="w-full flex items-center gap-3 bg-[#0b0b14] border border-dashed border-[#2a2a38] hover:border-violet-500/40 rounded-xl px-4 py-3 transition-all duration-150 group text-left"
              >
                <div className="w-10 h-8 rounded-lg bg-[#17171c] border border-[#2a2a38] flex items-center justify-center text-base flex-shrink-0">
                  🏷️
                </div>
                <div>
                  <p className="text-xs font-medium text-[#888] group-hover:text-white transition">
                    Upload brand logo
                  </p>
                  <p className="text-[10px] text-[#444]">PNG with transparency works best · JPG · WEBP · SVG · max 2 MB</p>
                </div>
                <div className="ml-auto text-[#555] text-xs border border-[#2a2a38] rounded-lg px-2 py-1 group-hover:border-violet-500/30 transition">
                  Browse
                </div>
              </button>
            )}

            {/* Hidden logo file input */}
            <input
              type="file"
              ref={logoInputRef}
              className="hidden"
              accept="image/png,image/jpeg,image/webp,image/svg+xml"
              onChange={handleLogoChange}
            />

            {/* Tip shown when logo is uploaded */}
            {logoFile && (
              <p className="text-[10px] text-[#444] mt-2 pl-1">
                Your logo will be placed top-left of the post and persists across generations until removed.
              </p>
            )}
          </div>

          {/* Prompt textarea */}
          <div className="relative mb-4">
            <textarea
              value={prompt}
              onChange={e => setPrompt(e.target.value)}
              rows={4}
              placeholder="Describe your image — brand name, headline, colors, mood, services, contact info..."
              className="w-full bg-[#0b0b14] border border-[#2a2a38] rounded-xl p-4 text-sm text-white placeholder-[#404055] focus:outline-none focus:border-violet-500/60 resize-none transition"
            />
            <div className="absolute bottom-3 right-3 text-[10px] text-[#404055]">{prompt.length} chars</div>
          </div>

          {/* Size selector */}
          <div className="flex gap-2 mb-4">
            {SIZE_OPTIONS.map(opt => (
              <button
                key={opt.value}
                onClick={() => setSize(opt.value)}
                className={`flex-1 rounded-xl py-2.5 px-3 text-left transition-all duration-150 border
                  ${size === opt.value
                    ? "border-violet-500/60 bg-violet-950/40 text-white"
                    : "border-[#2a2a38] bg-[#0b0b14] text-[#666] hover:border-violet-500/30 hover:text-[#aaa]"}`}
              >
                <div className="text-base mb-0.5">{opt.icon}</div>
                <div className="text-xs font-semibold">{opt.label}</div>
                <div className="text-[10px] text-[#555]">{opt.sub}</div>
              </button>
            ))}
          </div>

          {/* Submit */}
          <button
            onClick={handleSubmit}
            disabled={loading || !hasInput}
            className="w-full relative overflow-hidden rounded-xl py-3.5 font-semibold text-sm text-white transition-all duration-200
              disabled:opacity-30 disabled:cursor-not-allowed
              bg-gradient-to-r from-violet-600 to-blue-600 hover:from-violet-500 hover:to-blue-500
              shadow-lg shadow-violet-900/30 hover:shadow-violet-700/30"
          >
            {loading ? (
              <span className="flex items-center justify-center gap-2">
                <span className="w-4 h-4 border-2 border-white/40 border-t-white rounded-full animate-spin" />
                Pipeline Running...
              </span>
            ) : (
              <span className="flex items-center justify-center gap-2">
                🐙 Generate with Octopus
                {logoFile && <span className="text-[10px] opacity-60 font-normal">+ logo</span>}
              </span>
            )}
          </button>
        </div>

        {/* ── Pipeline steps viewer ── */}
        {pipelineVisible && (
          <div className="bg-[#0e0e18]/90 border border-white/6 rounded-2xl p-5 backdrop-blur-md">
            <div className="flex items-center gap-2 mb-5">
              <span className="text-xs font-bold text-[#9ea1a4] uppercase tracking-widest">Generation Pipeline</span>
              {loading && <span className="text-[10px] bg-violet-900/40 text-violet-300 border border-violet-800/40 px-2 py-0.5 rounded-full">Running</span>}
              {!loading && allDone && !hasError && <span className="text-[10px] bg-emerald-900/40 text-emerald-300 border border-emerald-800/40 px-2 py-0.5 rounded-full">Complete</span>}
              {!loading && hasError && <span className="text-[10px] bg-red-900/40 text-red-300 border border-red-800/40 px-2 py-0.5 rounded-full">Failed</span>}
            </div>
            <div className="space-y-0">
              {steps.map((step, idx) => (
                <div key={step.id} className="flex gap-3">
                  <div className="flex flex-col items-center">
                    <StepIcon status={step.status} />
                    {idx < steps.length - 1 && (
                      <div className={`w-px flex-1 my-1 ${step.status === "done" ? "bg-emerald-500/30" : "bg-[#232329]"}`} style={{ minHeight: "20px" }} />
                    )}
                  </div>
                  <div className={`pb-4 min-w-0 flex-1 ${idx === steps.length - 1 ? "pb-0" : ""}`}>
                    <p className={`text-sm font-medium leading-tight ${
                      step.status === "done"    ? "text-white"      :
                      step.status === "running" ? "text-violet-300" :
                      step.status === "error"   ? "text-red-400"    : "text-[#555]"
                    }`}>{step.label}</p>
                    {step.detail && <p className="text-[11px] text-[#666] mt-1 leading-relaxed truncate max-w-xl">{step.detail}</p>}
                  </div>
                </div>
              ))}
            </div>
            {errorMsg && (
              <div className="mt-4 bg-red-950/40 border border-red-900/50 rounded-xl p-4 text-xs text-red-300">
                <span className="font-bold">Error:</span> {errorMsg}
              </div>
            )}
          </div>
        )}

        {/* ── Generated image history ── */}
        {history.length > 0 && (
          <div className="space-y-5">
            <h2 className="text-xs font-bold text-[#9ea1a4] uppercase tracking-widest">Generated Assets</h2>
            {history.map(item => (
              <div key={item.id} className="bg-[#0e0e18]/90 border border-white/6 rounded-2xl p-5 backdrop-blur-md shadow-xl">
                <div className="flex justify-between items-center mb-4 pb-3 border-b border-white/5">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-[10px] bg-violet-900/40 text-violet-300 border border-violet-800/40 px-2 py-0.5 rounded font-mono font-bold uppercase">Asset Ready</span>
                    <span className="text-[10px] bg-[#1a1a22] text-[#888] border border-[#2a2a38] px-2 py-0.5 rounded">{item.canvasW} × {item.canvasH}</span>
                    {item.fileName && (
                      <span className="text-xs text-blue-400 flex items-center gap-1">
                        <FileTypeTag name={item.fileName} />{item.fileName}
                      </span>
                    )}
                  </div>
                  <a
                    href={`data:image/png;base64,${item.imageB64}`}
                    download={`octopus-${item.size}-${item.id}.png`}
                    className="text-xs bg-[#17171c] hover:bg-[#232329] border border-[#2a2a38] text-white px-3 py-1.5 rounded-lg transition flex items-center gap-1 shrink-0"
                  >
                    ↓ Download PNG
                  </a>
                </div>
                <div className="grid grid-cols-1 sm:grid-cols-5 gap-5 items-start">
                  <div className="sm:col-span-2 overflow-hidden rounded-xl border border-white/6 bg-[#080810] shadow-inner">
                    <img
                      src={`data:image/png;base64,${item.imageB64}`}
                      alt="Generated marketing post"
                      className="w-full h-auto object-contain"
                    />
                  </div>
                  <div className="sm:col-span-3 space-y-3">
                    <h3 className="text-xs font-semibold text-[#9ea1a4] uppercase tracking-wide">Input Prompt</h3>
                    <p className="text-xs text-[#c4c7c5] bg-[#0b0b14] p-3 rounded-xl border border-[#1e1e28] max-h-48 overflow-y-auto leading-relaxed italic">
                      &ldquo;{item.prompt || "Extracted from uploaded document."}&rdquo;
                    </p>
                    <div className="grid grid-cols-3 gap-2 pt-1">
                      {([["🎨", "AI Background"], ["✏️", "Text Composited"], ["📦", "PNG Exported"]] as [string, string][]).map(([icon, label]) => (
                        <div key={label} className="bg-emerald-950/30 border border-emerald-900/30 rounded-lg p-2 text-center">
                          <div className="text-base mb-0.5">{icon}</div>
                          <div className="text-[10px] text-emerald-400 font-medium">{label}</div>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}

        {/* Empty state */}
        {history.length === 0 && !pipelineVisible && (
          <div className="border border-dashed border-[#1e1e28] rounded-2xl p-16 text-center">
            <div className="text-5xl mb-4 opacity-30">🐙</div>
            <p className="text-sm text-[#444]">Your generated images will appear here</p>
          </div>
        )}
      </main>
    </div>
  );  
}