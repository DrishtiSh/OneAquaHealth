import Link from "next/link";
import { formatWeek, likelihoodLabel } from "@/lib/format";
import type { Incident } from "@/lib/types";

// Detected contamination incidents touching one site, with the most likely entry points.
export default function IncidentList({ incidents, siteId }: { incidents: Incident[]; siteId: string }) {
  if (incidents.length === 0) {
    return <p className="text-sm text-muted-foreground">No incidents have been detected at this site.</p>;
  }

  return (
    <ul className="divide-y divide-border-color">
      {incidents.map((inc) => {
        const sameWeek = inc.start_week === inc.end_week;
        return (
          <li key={inc.incident_id} className="py-3 flex flex-col gap-1">
            <div className="flex flex-wrap items-center gap-2 text-sm">
              <span className="font-medium text-foreground">
                {sameWeek
                  ? `Week of ${formatWeek(inc.start_week)}`
                  : `${formatWeek(inc.start_week)} – ${formatWeek(inc.end_week)}`}
              </span>
              <span
                className={`rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${
                  inc.max_alert_level === "confirmed"
                    ? "bg-rose-100 text-rose-700 dark:bg-rose-500/15 dark:text-rose-300"
                    : "bg-amber-100 text-amber-800 dark:bg-amber-500/15 dark:text-amber-300"
                }`}
              >
                {inc.max_alert_level}
              </span>
              {inc.is_recent && (
                <span className="rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide bg-accent/15 text-accent">
                  Recent
                </span>
              )}
              {inc.rain_week && <span className="text-xs text-muted-foreground">after heavy rain</span>}
              <span className="text-xs text-muted-foreground font-mono">{inc.incident_id}</span>
            </div>
            <p className="text-xs text-muted-foreground">
              Water-quality drop of about {Math.round(inc.peak_drop_W)} points across{" "}
              {inc.affected_site_ids.length} site{inc.affected_site_ids.length === 1 ? "" : "s"}.
              {inc.upstream_unobserved && " No one reported upstream at the time, so it may have entered further up."}
            </p>
            {inc.source_ranking.length > 0 && (
              <p className="text-xs text-muted-foreground">
                Likely entry point:{" "}
                {inc.source_ranking.slice(0, 3).map((s, i) => (
                  <span key={s.site_id}>
                    {i > 0 && ", "}
                    {s.site_id === siteId ? (
                      <span className="font-medium text-foreground">{s.name ?? s.site_id} (this site)</span>
                    ) : (
                      <Link href={`/site/${s.site_id}`} className="text-accent hover:underline">
                        {s.name ?? s.site_id}
                      </Link>
                    )}{" "}
                    {likelihoodLabel(s.prob)} ({Math.round(s.prob * 100)}%)
                  </span>
                ))}
              </p>
            )}
          </li>
        );
      })}
    </ul>
  );
}
