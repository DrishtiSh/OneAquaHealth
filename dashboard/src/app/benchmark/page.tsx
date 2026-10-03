import Link from "next/link";
import { getBenchmark, getSiteData } from "@/lib/data";
import { getScenario } from "@/lib/scenario";
import { formatWeek } from "@/lib/format";
import ApiOfflineBanner from "@/components/ApiOfflineBanner";
import type { BenchmarkEvent, BenchmarkReport, EventOutcome } from "@/lib/types";

export const metadata = { title: "How accurate is this? · OneAquaHealth" };

const pct = (x: number | null | undefined) => (x == null ? "n/a" : `${Math.round(100 * x)}%`);
const num = (x: number | null | undefined, nd = 1) => (x == null ? "n/a" : x.toFixed(nd));

const OUTCOME_STYLE: Record<EventOutcome, string> = {
  missed: "bg-rose-100 text-rose-700 dark:bg-rose-500/15 dark:text-rose-300",
  "detected (possible only)": "bg-amber-100 text-amber-800 dark:bg-amber-500/15 dark:text-amber-300",
  detected: "bg-emerald-100 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300",
};

export default async function BenchmarkPage() {
  const scenario = await getScenario();
  const [bench, siteData] = await Promise.all([getBenchmark(), getSiteData(scenario.variant, scenario.sensitivity)]);
  const names = Object.fromEntries(siteData.sites.map((s) => [s.site_id, s.name]));

  return (
    <main className="flex flex-1 flex-col gap-6 max-w-5xl mx-auto w-full px-6 py-8">
      <header className="flex flex-col gap-1">
        <h1 className="text-2xl font-semibold tracking-tight text-foreground">How accurate is this?</h1>
        <p className="text-sm text-muted-foreground max-w-3xl">
          We ran the whole pipeline on simulated citizen reports where the true answer is known, then
          checked every result against it, misses and false alarms included. The thresholds were
          fixed before this comparison and were not tuned to it.
        </p>
      </header>

      {bench.source === "fallback" && <ApiOfflineBanner />}
      {bench.source === "api" && !bench.report && (
        <p className="rounded-xl border border-border-color bg-surface p-4 text-sm text-muted-foreground">
          This snapshot has no benchmark. It only exists when the pipeline runs on simulated data, because
          real reports come without a known answer to score against.
        </p>
      )}
      {bench.report && <Report r={bench.report} names={names} />}
    </main>
  );
}

function Report({ r, names }: { r: BenchmarkReport; names: Record<string, string> }) {
  const h = r.headline;
  const sa = r.events.source_attribution;
  const site = (id: string) => (
    <Link href={`/site/${id}`} className="text-accent hover:underline whitespace-nowrap">
      {names[id] ?? id}
    </Link>
  );
  const events = [...r.events.events].sort(
    (a, b) => Number(a.outcome !== "missed") - Number(b.outcome !== "missed") || a.start_week.localeCompare(b.start_week),
  );

  return (
    <>
      <div className="rounded-xl border border-sky-300/60 bg-sky-50 dark:bg-sky-500/10 dark:border-sky-500/30 px-4 py-3 text-sm text-sky-900 dark:text-sky-200">
        <span className="font-semibold">Simulated data.</span> {r.data.n_sites} sites &times; {r.data.n_weeks} weeks (
        {formatWeek(r.data.first_week)} to {formatWeek(r.data.latest_week)}), {r.data.n_reports} citizen reports. These
        numbers show how the method behaves when the answer is known; real-world accuracy is unknown until it is
        compared with lab samples or confirmed reports.
      </div>

      <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
        <Tile value={`${h.n_events_detected} of ${h.n_true_events}`} label="contamination events found" sub={`${r.events.n_detected_confirmed} at the confirmed level`} />
        <Tile value={`${h.n_false_alarms} of ${h.n_incidents}`} label="reported incidents were false alarms" sub={`incident precision ${pct(h.incident_precision)}`} />
        <Tile value={pct(h.site_week_precision)} label="of weekly alerts were real" sub="normal sensitivity, confirmed or possible" />
        <Tile value={pct(h.site_week_recall_observed)} label="of real changes flagged, on weeks with a report" sub={`${pct(h.site_week_recall)} of all real changes, including unreported weeks`} />
        <Tile value={pct(h.source_top1_accuracy)} label="entry point named correctly" sub={`true source in the shortlist ${pct(sa.credible_set_coverage)} of the time`} />
        <Tile value={pct(h.W_coverage_90)} label="of the time the true water quality fell inside the 90% range" sub={`average error ${num(h.W_mae)} points`} />
      </div>

      <Section title="Every true contamination event" hint="Misses first. Reports counts citizen reports during the part of the event large enough to detect.">
        <Table head={["Weeks", "What happened", "Where it started", "Peak drop", "Reports", "Outcome", "Why / matched incident"]}>
          {events.map((e) => (
            <tr key={e.event_id}>
              <Td nowrap>{weeks(e.start_week, e.end_week)}</Td>
              <Td>
                {e.event_type.replaceAll("_", " ")}
                {e.rain_triggered && <span className="text-muted-foreground"> &middot; after rain</span>}
              </Td>
              <Td>{site(e.source_site_id)}</Td>
              <Td>{Math.round(e.peak_drop_W)} pts</Td>
              <Td>{e.reports_in_footprint}</Td>
              <Td>
                <Outcome outcome={e.outcome} />
              </Td>
              <Td>{whyText(e, names)}</Td>
            </tr>
          ))}
        </Table>
      </Section>

      <Section title="False alarms" hint="Reported incidents that matched no true event.">
        {r.events.false_alarms.length === 0 ? (
          <p className="text-sm text-muted-foreground">None.</p>
        ) : (
          <Table head={["Incident", "Weeks", "Sites", "Level", "What really happened"]}>
            {r.events.false_alarms.map((f) => (
              <tr key={f.incident_id}>
                <Td mono>{f.incident_id}</Td>
                <Td nowrap>{weeks(f.start_week, f.end_week)}</Td>
                <Td>
                  {f.affected_site_ids.map((id, i) => (
                    <span key={id}>
                      {i > 0 && ", "}
                      {site(id)}
                    </span>
                  ))}
                </Td>
                <Td>{f.max_alert_level}</Td>
                <Td>{f.what_really_happened}</Td>
              </tr>
            ))}
          </Table>
        )}
      </Section>

      <Section title="Do the probability words mean what they say?" hint="Every site-week, grouped by the word the findings would use for its change probability (primary model, normal sensitivity).">
        <Table head={["Word used", "Site-weeks", "Really changed", "Share"]}>
          {r.site_week_detection.calibration.map((c) => (
            <tr key={c.band}>
              <Td>{c.band}</Td>
              <Td>{c.n_site_weeks}</Td>
              <Td>{c.n_truly_changed}</Td>
              <Td>{pct(c.share_truly_changed)}</Td>
            </tr>
          ))}
        </Table>
      </Section>

      <Section
        title="Weekly alerts by scenario"
        hint={`The dashboard's toggles. Recall counts real changes flagged; "on reported weeks" leaves out weeks nobody reported from. No-model baseline (${r.site_week_detection.baseline.rule}): precision ${pct(r.site_week_detection.baseline.precision)}, recall on reported weeks ${pct(r.site_week_detection.baseline.recall_observed_weeks)}.`}
      >
        <Table head={["Rain assumption", "Sensitivity", "Counts as alert", "Real changes", "Flagged right", "False", "Missed", "Precision", "Recall", "Recall on reported weeks"]}>
          {r.site_week_detection.by_variant_and_sensitivity.map((g) => (
            <tr key={`${g.model_variant}-${g.sensitivity}-${g.rule}`}>
              <Td>{g.model_variant === "M1" ? "On" : "Off"}</Td>
              <Td>
                {g.sensitivity} ({g.delta_W})
              </Td>
              <Td>{g.rule === "confirmed" ? "confirmed" : "confirmed or possible"}</Td>
              <Td>{g.n_truly_changed}</Td>
              <Td>{g.tp}</Td>
              <Td>{g.fp}</Td>
              <Td>{g.fn}</Td>
              <Td>{pct(g.precision)}</Td>
              <Td>{pct(g.recall)}</Td>
              <Td>{pct(g.recall_observed_weeks)}</Td>
            </tr>
          ))}
        </Table>
      </Section>

      <Section title="Score accuracy" hint="Weekly estimate (median) vs the true index, primary model. The 90% range should contain the truth about 90% of the time.">
        <Table head={["Score", "Weeks", "n", "Average error", "Inside 90% range", "Range width"]}>
          {(["W", "H"] as const).flatMap((score) =>
            Object.entries(r.score_accuracy.M1?.[score] ?? {})
              .filter(([, m]) => m.n > 0)
              .map(([subset, m]) => (
                <tr key={`${score}-${subset}`}>
                  <Td>{score === "W" ? "Water quality" : "Health risk"}</Td>
                  <Td>{subset.replace("evidence_", "evidence: ").replaceAll("_", " ")}</Td>
                  <Td>{m.n}</Td>
                  <Td>{num(m.mae)} pts</Td>
                  <Td>{pct(m.coverage_90)}</Td>
                  <Td>{num(m.mean_interval_width)} pts</Td>
                </tr>
              )),
          )}
        </Table>
      </Section>

      <Section
        title="Rain and overflow pattern"
        hint={`${pct(r.rain_pattern.share_of_events_rain_triggered)} of the ${r.rain_pattern.n_events} simulated events were triggered by rain. "Rate ratio" compares how often water quality truly dropped in rain-exposed vs dry weeks.`}
      >
        <Table head={["Sites", "True rate ratio", "Estimated (90% range)", "Range contains truth", "Verdict", "Judged"]}>
          {r.rain_pattern.groups.map((g) => (
            <tr key={g.group}>
              <Td>{g.group.replace("_", " ")}</Td>
              <Td>{num(g.true_irr_observed_weeks, 2)}</Td>
              <Td nowrap>
                {num(g.estimated_irr_median, 2)} ({num(g.estimated_irr_q05, 2)}&ndash;{num(g.estimated_irr_q95, 2)})
              </Td>
              <Td>{g.interval_contains_truth ? "yes" : "no"}</Td>
              <Td>{g.verdict}</Td>
              <Td>{g.verdict_judged}</Td>
            </tr>
          ))}
        </Table>
      </Section>

      <Section title="Caveats">
        <ul className="list-disc pl-5 text-sm text-muted-foreground flex flex-col gap-1">
          {r.caveats.map((c) => (
            <li key={c}>{c}</li>
          ))}
        </ul>
      </Section>
    </>
  );
}

function weeks(start: string, end: string) {
  return start === end ? `week of ${formatWeek(start)}` : `${formatWeek(start)} – ${formatWeek(end)}`;
}

function whyText(e: BenchmarkEvent, names: Record<string, string>) {
  if (e.outcome === "missed") return e.miss_reason;
  const found = e.found_source
    ? `; entry point ${e.source_correct ? "right" : `wrong (named ${names[e.found_source] ?? e.found_source})`}`
    : "";
  return `${e.matched_incidents.join(", ")}${found}`;
}

function Outcome({ outcome }: { outcome: EventOutcome }) {
  return (
    <span className={`rounded px-1.5 py-0.5 text-[11px] font-semibold whitespace-nowrap ${OUTCOME_STYLE[outcome]}`}>
      {outcome === "detected (possible only)" ? "found (possible)" : outcome === "detected" ? "found" : "missed"}
    </span>
  );
}

function Tile({ value, label, sub }: { value: string; label: string; sub: string }) {
  return (
    <div className="rounded-xl border border-border-color bg-surface shadow-sm px-4 py-3">
      <p className="text-2xl font-semibold text-foreground">{value}</p>
      <p className="text-xs text-foreground mt-0.5">{label}</p>
      <p className="text-xs text-muted-foreground mt-1">{sub}</p>
    </div>
  );
}

function Section({ title, hint, children }: { title: string; hint?: string; children: React.ReactNode }) {
  return (
    <section className="rounded-xl border border-border-color bg-surface shadow-sm p-4 flex flex-col gap-2">
      <div>
        <h2 className="text-sm font-semibold text-foreground">{title}</h2>
        {hint && <p className="text-xs text-muted-foreground mt-0.5">{hint}</p>}
      </div>
      {children}
    </section>
  );
}

function Table({ head, children }: { head: string[]; children: React.ReactNode }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-sm">
        <thead className="text-xs text-muted-foreground">
          <tr>
            {head.map((h) => (
              <th key={h} className="px-2 py-1.5 font-medium whitespace-nowrap">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-border-color text-foreground">{children}</tbody>
      </table>
    </div>
  );
}

function Td({ children, nowrap = false, mono = false }: { children: React.ReactNode; nowrap?: boolean; mono?: boolean }) {
  return (
    <td className={`px-2 py-1.5 align-top ${nowrap ? "whitespace-nowrap" : ""} ${mono ? "font-mono text-xs" : ""}`}>
      {children}
    </td>
  );
}
