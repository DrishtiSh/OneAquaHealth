import Link from "next/link";
import { notFound } from "next/navigation";
import {
  getSite,
  getSites,
  getOrderedSiteIds,
  getWeatherForSite,
  getExposureForSite,
  getRiskSummaryForSite,
} from "@/lib/data";
import RainfallChart from "@/components/RainfallChart";
import RiverChain from "@/components/RiverChain";
import ExposureList from "@/components/ExposureList";
import MockDataBanner from "@/components/MockDataBanner";
import StatusBadge from "@/components/StatusBadge";
import FavoriteButton from "@/components/FavoriteButton";
import SiteNotes from "@/components/SiteNotes";

export default async function SiteDetailPage(props: PageProps<"/site/[siteId]">) {
  const { siteId } = await props.params;
  const site = getSite(siteId);
  if (!site) notFound();

  const sites = getSites();
  const sitesById = new Map(sites.map((s) => [s.site_id, s]));
  const orderedSiteIds = getOrderedSiteIds();
  const weeks = getWeatherForSite(siteId);
  const exposure = getExposureForSite(siteId);
  const { data: risk, isMock } = await getRiskSummaryForSite(siteId);

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

      {isMock && <MockDataBanner />}

      <section className="rounded-xl border border-border-color bg-surface shadow-sm p-4">
        <h2 className="text-sm font-semibold text-foreground mb-2">Position in the river chain</h2>
        <RiverChain orderedSiteIds={orderedSiteIds} sitesById={sitesById} currentSiteId={siteId} />
      </section>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <section className="rounded-xl border border-border-color bg-surface shadow-sm p-4">
          <h2 className="text-sm font-semibold text-foreground mb-2">Rainfall history</h2>
          {weeks.length > 0 ? (
            <RainfallChart weeks={weeks} />
          ) : (
            <p className="text-sm text-muted-foreground">No weather data available.</p>
          )}
        </section>

        <section className="rounded-xl border border-border-color bg-surface shadow-sm p-4">
          <h2 className="text-sm font-semibold text-foreground mb-2">Nearby exposure points</h2>
          <ExposureList items={exposure} />
        </section>
      </div>

      <section className="rounded-xl border border-border-color bg-surface shadow-sm p-4">
        <h2 className="text-sm font-semibold text-foreground mb-2">Your notes</h2>
        <SiteNotes siteId={siteId} />
      </section>

      {risk && (
        <section className="rounded-xl border border-border-color bg-surface shadow-sm p-4">
          <h2 className="text-sm font-semibold text-foreground mb-3 flex items-center gap-2">
            Risk assessment
            {isMock && (
              <span className="text-[10px] font-semibold uppercase tracking-wide text-amber-700 dark:text-amber-300 bg-amber-100 dark:bg-amber-500/15 px-1.5 py-0.5 rounded">
                Mock
              </span>
            )}
          </h2>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mb-4">
            <div className="rounded-lg bg-surface-muted px-4 py-3">
              <p className="text-xs text-muted-foreground">Water quality (W)</p>
              <p className="text-2xl font-semibold text-foreground">
                {risk.water_quality_score.toFixed(0)}
              </p>
              <p className="text-xs text-muted-foreground">
                range {risk.water_quality_uncertainty[0].toFixed(0)}&ndash;
                {risk.water_quality_uncertainty[1].toFixed(0)}
              </p>
            </div>
            <div className="rounded-lg bg-surface-muted px-4 py-3">
              <p className="text-xs text-muted-foreground">Health risk (H)</p>
              <p className="text-2xl font-semibold text-foreground">
                {risk.health_risk_score.toFixed(0)}
              </p>
              <p className="text-xs text-muted-foreground">
                range {risk.health_risk_uncertainty[0].toFixed(0)}&ndash;
                {risk.health_risk_uncertainty[1].toFixed(0)}
              </p>
            </div>
          </div>
          <p className="text-sm text-foreground leading-relaxed">{risk.finding}</p>
        </section>
      )}
    </main>
  );
}
