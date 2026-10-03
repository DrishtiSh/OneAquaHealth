import { getSites, getRiskSummaries } from "@/lib/data";
import SiteMapLoader from "@/components/SiteMapLoader";
import MockDataBanner from "@/components/MockDataBanner";
import YourSites from "@/components/YourSites";
import type { SiteRiskSummary } from "@/lib/types";

export default async function OverviewPage() {
  const sites = getSites();
  const { data: riskSummaries, isMock } = await getRiskSummaries();
  const riskBySiteId = Object.fromEntries(
    riskSummaries.map((r) => [r.site_id, r])
  ) as Record<string, SiteRiskSummary>;

  const elevatedCount = riskSummaries.filter((r) => r.status === "elevated_risk").length;
  const normalCount = riskSummaries.filter((r) => r.status === "normal").length;
  const insufficientCount = riskSummaries.filter((r) => r.status === "insufficient_evidence").length;

  return (
    <main className="flex flex-1 flex-col gap-6 max-w-5xl mx-auto w-full px-6 py-8">
      <header className="flex flex-col gap-1">
        <h1 className="text-2xl font-semibold tracking-tight text-foreground">Stream health overview</h1>
        <p className="text-sm text-muted-foreground">
          Citizen stream observations, real weather and geography, turned into stream-health insight.
          Use the sidebar to search or filter sites by status.
        </p>
      </header>

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <StatCard label="Monitoring sites" value={sites.length} />
        <StatCard label="Elevated risk" value={elevatedCount} accent="text-rose-600 dark:text-rose-400" />
        <StatCard label="Normal" value={normalCount} accent="text-emerald-600 dark:text-emerald-400" />
        <StatCard label="Insufficient evidence" value={insufficientCount} accent="text-muted-foreground" />
      </div>

      {isMock && <MockDataBanner />}

      <YourSites sites={sites} riskBySiteId={riskBySiteId} />

      <section className="rounded-xl border border-border-color bg-surface shadow-sm overflow-hidden">
        <div className="border-b border-border-color px-4 py-3">
          <h2 className="text-sm font-semibold text-foreground">Monitoring sites</h2>
        </div>
        <div className="h-112">
          <SiteMapLoader sites={sites} riskBySiteId={riskBySiteId} />
        </div>
      </section>
    </main>
  );
}

function StatCard({
  label,
  value,
  accent = "text-foreground",
}: {
  label: string;
  value: number;
  accent?: string;
}) {
  return (
    <div className="rounded-xl border border-border-color bg-surface shadow-sm px-4 py-3">
      <p className={`text-2xl font-semibold ${accent}`}>{value}</p>
      <p className="text-xs text-muted-foreground mt-0.5">{label}</p>
    </div>
  );
}
