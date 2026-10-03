"use client";

import Link from "next/link";
import { useAuth } from "@/lib/auth-context";
import StatusBadge from "@/components/StatusBadge";
import type { Site, SiteRiskSummary } from "@/lib/types";

interface YourSitesProps {
  sites: Site[];
  riskBySiteId: Record<string, SiteRiskSummary>;
}

// Additive, not a gate: the public overview below still shows all 10 sites
// regardless of login. This just surfaces favorites first for signed-in users.
export default function YourSites({ sites, riskBySiteId }: YourSitesProps) {
  const { user, favoriteSiteIds } = useAuth();

  if (!user || favoriteSiteIds.size === 0) return null;

  const favoriteSites = sites.filter((s) => favoriteSiteIds.has(s.site_id));

  return (
    <section className="rounded-xl border border-border-color bg-surface shadow-sm overflow-hidden">
      <div className="border-b border-border-color px-4 py-3">
        <h2 className="text-sm font-semibold text-foreground">&hearts; Your sites</h2>
      </div>
      <div className="divide-y divide-border-color">
        {favoriteSites.map((site) => {
          const risk = riskBySiteId[site.site_id];
          return (
            <Link
              key={site.site_id}
              href={`/site/${site.site_id}`}
              className="flex items-center justify-between px-4 py-3 hover:bg-surface-muted transition-colors"
            >
              <span className="text-sm font-medium text-foreground">{site.name}</span>
              {risk && <StatusBadge status={risk.status} />}
            </Link>
          );
        })}
      </div>
    </section>
  );
}
