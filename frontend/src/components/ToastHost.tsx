"use client";

import { AlertTriangle, CheckCircle2, Info, X } from "lucide-react";

import { useGraphStore } from "@/store/useGraphStore";

const TONES = {
  info: { border: "border-sky-500/30", bg: "bg-sky-500/10", text: "text-sky-300", icon: Info },
  success: {
    border: "border-emerald-500/30",
    bg: "bg-emerald-500/10",
    text: "text-emerald-300",
    icon: CheckCircle2,
  },
  error: {
    border: "border-rose-500/30",
    bg: "bg-rose-500/10",
    text: "text-rose-300",
    icon: AlertTriangle,
  },
} as const;

export function ToastHost() {
  const toast = useGraphStore((state) => state.toast);
  const dismiss = useGraphStore((state) => state.dismissToast);
  if (!toast) return null;

  const tone = TONES[toast.tone];
  const Icon = tone.icon;

  return (
    <div className="pointer-events-none fixed right-4 top-16 z-[60] w-[min(92vw,22rem)]">
      <div
        className={`rise-in pointer-events-auto flex items-start gap-2.5 rounded-xl border ${tone.border} ${tone.bg} p-3 shadow-glass backdrop-blur-xl`}
        role="status"
      >
        <Icon size={14} className={`mt-0.5 shrink-0 ${tone.text}`} />
        <p className="flex-1 text-[11px] leading-relaxed text-slate-200">{toast.message}</p>
        <button
          type="button"
          onClick={dismiss}
          className="rounded p-0.5 text-slate-400 transition-colors hover:text-white"
          aria-label="Dismiss notification"
        >
          <X size={12} />
        </button>
      </div>
    </div>
  );
}
