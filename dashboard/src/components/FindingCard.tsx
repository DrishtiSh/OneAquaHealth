import type { Finding, FindingPriority } from "@/lib/types";

const PRIORITY_STYLE: Record<FindingPriority, { label: string; className: string }> = {
  high: { label: "High priority", className: "bg-rose-100 text-rose-700 dark:bg-rose-500/15 dark:text-rose-300" },
  medium: { label: "Medium", className: "bg-amber-100 text-amber-800 dark:bg-amber-500/15 dark:text-amber-300" },
  low: { label: "Low", className: "bg-slate-200 text-slate-700 dark:bg-slate-500/20 dark:text-slate-300" },
  info: { label: "Info", className: "bg-sky-100 text-sky-700 dark:bg-sky-500/15 dark:text-sky-300" },
};

// A fact-locked finding from Stage 7: the text is shown exactly as the pipeline wrote it.
export default function FindingCard({ finding, compact = false }: { finding: Finding; compact?: boolean }) {
  const priority = PRIORITY_STYLE[finding.priority];
  return (
    <article className="rounded-lg border border-border-color bg-surface px-4 py-3 flex flex-col gap-1.5">
      <div className="flex flex-wrap items-center gap-1.5">
        <span className={`rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${priority.className}`}>
          {priority.label}
        </span>
        {finding.is_recent && (
          <span className="rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide bg-accent/15 text-accent">
            Recent
          </span>
        )}
        {finding.confidence_label && (
          <span className="text-[11px] text-muted-foreground">{finding.confidence_label}</span>
        )}
      </div>
      <h3 className="text-sm font-semibold text-foreground leading-snug">{finding.headline}</h3>
      <p className={`text-sm text-muted-foreground leading-relaxed ${compact ? "line-clamp-3" : ""}`}>
        {finding.body}
      </p>
      {finding.precaution && (
        <p className="text-sm text-foreground border-l-2 border-amber-400 pl-2">{finding.precaution}</p>
      )}
      {!compact && finding.caveats.length > 0 && (
        <ul className="text-xs text-muted-foreground list-disc pl-4">
          {finding.caveats.map((c) => (
            <li key={c}>{c}</li>
          ))}
        </ul>
      )}
    </article>
  );
}
