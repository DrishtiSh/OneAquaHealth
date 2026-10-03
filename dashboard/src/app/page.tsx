import Link from "next/link";
import { getOverviewFindings, getSiteData } from "@/lib/data";
import { getScenario } from "@/lib/scenario";
import { formatWeek } from "@/lib/format";
import SiteMapLoader from "@/components/SiteMapLoader";
import ApiOfflineBanner from "@/components/ApiOfflineBanner";
import FindingCard from "@/components/FindingCard";
import YourSites from "@/components/YourSites";

export default async function OverviewPage() {
  const scenario = await getScenario();
  const [siteData, findings] = await Promise.all([
    getSiteData(scenario.variant, scenario.sensitivity),
    getOverviewFindings(),
  ]);
  const { sites, riskBySiteId, snapshot } = siteData;
  const statuses = Object.values(riskBySiteId).map((r) => r.status);
  const count = (s: string) => statuses.filter((x) => x === s).length;

  return (
    <main className="flex flex-1 flex-col gap-6 max-w-5xl mx-auto w-full px-6 py-8">
      <header className="flex flex-col gap-1">
        <h1 className="text-2xl font-semibold tracking-tight text-foreground">Stream health overview</h1>
        <p className="text-sm text-muted-foreground">
          Citizen stream observations, real weather and geography, turned into stream-health insight.
          {snapshot && <> Showing the week of {formatWeek(snapshot.latest_week)}.</>} Use the sidebar to
          search or filter sites by status.
        </p>
      </header>

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <StatCard label="Monitoring sites" value={sites.length} />
        <StatCard label="Elevated risk" value={count("elevated_risk")} accent="text-rose-600 dark:text-rose-400" />
        <StatCard label="Normal" value={count("normal")} accent="text-emerald-600 dark:text-emerald-400" />
        <StatCard label="Insufficient evidence" value={count("insufficient_evidence")} accent="text-muted-foreground" />
      </div>

      {siteData.source === "fallback" && <ApiOfflineBanner />}

      <YourSites sites={sites} riskBySiteId={riskBySiteId} />

      <section className="rounded-xl border border-border-color bg-surface shadow-sm overflow-hidden">
        <div className="border-b border-border-color px-4 py-3">
          <h2 className="text-sm font-semibold text-foreground">Monitoring sites</h2>
        </div>
        <div className="h-112">
          <SiteMapLoader sites={sites} riskBySiteId={riskBySiteId} />
        </div>
      </section>

      {findings.source === "api" && (findings.top.length > 0 || findings.rainPattern) && (
        <section className="flex flex-col gap-3">
          <div>
            <h2 className="text-sm font-semibold text-foreground">Latest findings</h2>
            <p className="text-xs text-muted-foreground">
              Detected contamination events, most important first. Written for the primary model at
              normal sensitivity, so the scenario toggles don&apos;t change them.
            </p>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {findings.top.map((f) => (
              <FindingLink key={f.finding_id} siteId={siteForFinding(f.facts)}>
                <FindingCard finding={f} compact />
              </FindingLink>
            ))}
          </div>
          {findings.rainPattern && (
            <div>
              <h2 className="text-sm font-semibold text-foreground mb-2">Rain and overflow pattern</h2>
              <FindingCard finding={findings.rainPattern} />
            </div>
          )}
        </section>
      )}
    </main>
  );
}

// Incident findings name their top source site in facts.top_source (value = site id).
function siteForFinding(facts: Record<string, { value: unknown }>): string | null {
  const v = facts.top_source?.value ?? facts.site0?.value;
  return typeof v === "string" ? v : null;
}

function FindingLink({ siteId, children }: { siteId: string | null; children: React.ReactNode }) {
  if (!siteId) return <>{children}</>;
  return (
    <Link href={`/site/${siteId}`} className="block rounded-lg hover:ring-2 hover:ring-accent/40 transition-shadow">
      {children}
    </Link>
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
