import type { RiskStatus } from "@/lib/types";

const STATUS_STYLE: Record<RiskStatus, { badge: string; dot: string; label: string }> = {
  elevated_risk: {
    badge: "bg-rose-100 text-rose-700 dark:bg-rose-500/15 dark:text-rose-300",
    dot: "bg-rose-500",
    label: "Elevated risk",
  },
  normal: {
    badge: "bg-emerald-100 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300",
    dot: "bg-emerald-500",
    label: "Normal",
  },
  insufficient_evidence: {
    badge: "bg-slate-200 text-slate-600 dark:bg-slate-500/20 dark:text-slate-300",
    dot: "bg-slate-400",
    label: "Insufficient evidence",
  },
};

export default function StatusBadge({ status }: { status: RiskStatus }) {
  const style = STATUS_STYLE[status];
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium ${style.badge}`}
    >
      <span className={`h-1.5 w-1.5 rounded-full ${style.dot}`} />
      {style.label}
    </span>
  );
}

export function statusDotColor(status: RiskStatus): string {
  return { elevated_risk: "#e11d48", normal: "#10b981", insufficient_evidence: "#94a3b8" }[status];
}
