import Link from "next/link";
import { notFound } from "next/navigation";
import { getSiteData, getSiteDetail, getSiteObservations, getSiteTimeseries } from "@/lib/data";
import { getScenario } from "@/lib/scenario";
import { formatWeek } from "@/lib/format";
import RainfallChart from "@/components/RainfallChart";
import RiverChain from "@/components/RiverChain";
import ExposureList from "@/components/ExposureList";
import ApiOfflineBanner from "@/components/ApiOfflineBanner";
import StatusBadge from "@/components/StatusBadge";
import FavoriteButton from "@/components/FavoriteButton";
import SiteNotes from "@/components/SiteNotes";
import ScoreTrendChart from "@/components/ScoreTrendChart";
import FindingCard from "@/components/FindingCard";
import IncidentList from "@/components/IncidentList";
import ObservationList from "@/components/ObservationList";
import type { Evidence } from "@/lib/types";

const EVIDENCE_TEXT: Record<Evidence, string> = {
  sufficient: "Enough direct reports to back this estimate.",
  weak: "Few direct reports, so treat this estimate with care.",
  insufficient: "Not enough direct reports this week; the estimate rests on earlier weeks, not new observations.",
};

export default async function SiteDetailPage(props: PageProps<"/site/[siteId]">) {
  const { siteId } = await props.params;
  const scenario = await getScenario();
  const siteData = await getSiteData(scenario.variant, scenario.sensitivity);
  const site = siteData.sites.find((s) => s.site_id === siteId);
  if (!site) notFound();

  const [detail, timeseries, reports] = await Promise.all([
    getSiteDetail(siteId, scenario.variant, scenario.sensitivity),
    getSiteTimeseries(siteId, scenario.variant, scenario.sensitivity),
    getSiteObservations(siteId),
  ]);

  const sitesById = new Map(siteData.sites.map((s) => [s.site_id, s]));
  const risk = siteData.riskBySiteId[siteId];
  const exposure = siteData.exposureBySiteId[siteId] ?? [];
  const isLive = siteData.source === "api";
  // Site-status findings repeat the status headline shown above, so list the rest.
  const findings = (detail.detail?.findings ?? []).filter((f) => f.finding_type !== "site_status");
  const incidents = detail.detail?.incidents ?? [];

  return (
    <main className="flex flex-1 flex-col gap-6 max-w-5xl mx-auto w-full px-6 py-8">
      <Link
        href="/"
        className="inline-flex w-fit items-center gap-1 text-sm text-muted-foreground hover:text-accent transition-colors"
      >
        &larr; Back to overview
      </Link>

      <header className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-foreground">{site.name}</h1>
          <p className="text-sm text-muted-foreground mt-0.5">
            {site.site_id} &middot; {site.watershed} &middot;{" "}
            {Math.round(site.distance_from_mouth_m)}m from the mouth
            {site.is_cso_outfall_adjacent && <> &middot; next to a sewer overflow outfall</>}
          </p>
          {site.known_context_note && (
            <p className="text-sm text-muted-foreground mt-2 max-w-xl">{site.known_context_note}</p>
          )}
        </div>
        <div className="flex items-center gap-3">
          <FavoriteButton siteId={siteId} />
          {risk && <StatusBadge status={risk.status} />}
        </div>
      </header>

      {!isLive && <ApiOfflineBanner />}

      {risk && (
        <section className="rounded-xl border border-border-color bg-surface shadow-sm p-4">
          <h2 className="text-sm font-semibold text-foreground mb-3 flex flex-wrap items-center gap-2">
            This week
            <span className="font-normal text-muted-foreground">(week of {formatWeek(risk.week_start)})</span>
            {!isLive && (
              <span className="text-[10px] font-semibold uppercase tracking-wide text-amber-700 dark:text-amber-300 bg-amber-100 dark:bg-amber-500/15 px-1.5 py-0.5 rounded">
                Mock
              </span>
            )}
          </h2>
          {risk.finding && <p className="text-sm font-medium text-foreground mb-1">{risk.finding}</p>}
          {risk.finding_body && <p className="text-sm text-muted-foreground leading-relaxed mb-3">{risk.finding_body}</p>}
          {isLive && !risk.finding && siteData.note && (
            <p className="text-xs text-muted-foreground mb-3">{siteData.note}</p>
          )}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <ScoreTile
              label="Water quality (W)"
              hint="0-100, higher is cleaner"
              value={risk.water_quality_score}
              range={risk.water_quality_uncertainty}
            />
            <ScoreTile
              label="Health risk (H)"
              hint="0-100, higher is riskier"
              value={risk.health_risk_score}
              range={risk.health_risk_uncertainty}
            />
          </div>
          {risk.evidence && (
            <p className="text-xs text-muted-foreground mt-3">
              Evidence: <span className="font-medium text-foreground">{risk.evidence}</span>
              {risk.n_reports != null && <> &middot; {risk.n_reports} report{risk.n_reports === 1 ? "" : "s"} this week</>}
              {risk.mixing_flag && <> &middot; reports disagree with each other</>}. {EVIDENCE_TEXT[risk.evidence]}
            </p>
          )}
        </section>
      )}

      {timeseries.weeks.length > 0 && (
        <section className="rounded-xl border border-border-color bg-surface shadow-sm p-4">
          <h2 className="text-sm font-semibold text-foreground mb-1">Two-year trend</h2>
          {timeseries.note && <p className="text-xs text-muted-foreground mb-3">{timeseries.note}</p>}
          <ScoreTrendChart weeks={timeseries.weeks} />
        </section>
      )}

      <section className="rounded-xl border border-border-color bg-surface shadow-sm p-4">
        <h2 className="text-sm font-semibold text-foreground mb-2">Position in the river chain</h2>
        <RiverChain orderedSiteIds={siteData.orderedSiteIds} sitesById={sitesById} currentSiteId={siteId} />
      </section>

      {detail.detail && (
        <section className="rounded-xl border border-border-color bg-surface shadow-sm p-4 flex flex-col gap-4">
          <div>
            <h2 className="text-sm font-semibold text-foreground mb-1">Detected incidents</h2>
            <p className="text-xs text-muted-foreground">
              Linked at normal sensitivity, so the sensitivity toggle doesn&apos;t change this list.
            </p>
            <IncidentList incidents={incidents} siteId={siteId} />
          </div>
          {findings.length > 0 && (
            <div className="flex flex-col gap-3">
              <h2 className="text-sm font-semibold text-foreground">Findings involving this site</h2>
              {findings.map((f) => (
                <FindingCard key={f.finding_id} finding={f} />
              ))}
            </div>
          )}
        </section>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <section className="rounded-xl border border-border-color bg-surface shadow-sm p-4">
          <h2 className="text-sm font-semibold text-foreground mb-2">Rainfall history</h2>
          {timeseries.rainfall.length > 0 ? (
            <RainfallChart weeks={timeseries.rainfall} />
          ) : (
            <p className="text-sm text-muted-foreground">No weather data available.</p>
          )}
        </section>

        <section className="rounded-xl border border-border-color bg-surface shadow-sm p-4">
          <h2 className="text-sm font-semibold text-foreground mb-2">Nearby exposure points</h2>
          <ExposureList items={exposure} />
        </section>
      </div>

      {reports.source === "api" && (
        <section className="rounded-xl border border-border-color bg-surface shadow-sm p-4">
          <h2 className="text-sm font-semibold text-foreground mb-2">Recent citizen reports</h2>
          <ObservationList observations={reports.observations} total={reports.total} />
        </section>
      )}

      <section className="rounded-xl border border-border-color bg-surface shadow-sm p-4">
        <h2 className="text-sm font-semibold text-foreground mb-2">Your notes</h2>
        <SiteNotes siteId={siteId} />
      </section>
    </main>
  );
}

function ScoreTile({
  label,
  hint,
  value,
  range,
}: {
  label: string;
  hint: string;
  value: number;
  range: [number, number];
}) {
  return (
    <div className="rounded-lg bg-surface-muted px-4 py-3">
      <p className="text-xs text-muted-foreground">
        {label} <span className="opacity-75">&middot; {hint}</span>
      </p>
      <p className="text-2xl font-semibold text-foreground">{value.toFixed(0)}</p>
      <p className="text-xs text-muted-foreground">
        likely {range[0].toFixed(0)}&ndash;{range[1].toFixed(0)} (90% interval)
      </p>
    </div>
  );
}
