"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { statusDotColor } from "@/components/StatusBadge";
import ScenarioToggles from "@/components/ScenarioToggles";
import { useAuth } from "@/lib/auth-context";
import type { RiskStatus, Scenario, ScenarioOptions, Site, SiteRiskSummary } from "@/lib/types";

type FilterValue = "all" | RiskStatus;

const FILTERS: { value: FilterValue; label: string }[] = [
  { value: "all", label: "All" },
  { value: "elevated_risk", label: "Elevated risk" },
  { value: "normal", label: "Normal" },
  { value: "insufficient_evidence", label: "Insufficient evidence" },
];

interface SidebarProps {
  sites: Site[];
  orderedSiteIds: string[];
  riskBySiteId: Record<string, SiteRiskSummary>;
  scenario: Scenario;
  scenarioOptions: ScenarioOptions;
  isOpenMobile: boolean;
  onClose: () => void;
}

export default function Sidebar({
  sites,
  orderedSiteIds,
  riskBySiteId,
  scenario,
  scenarioOptions,
  isOpenMobile,
  onClose,
}: SidebarProps) {
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState<FilterValue>("all");
  const [favoritesOnly, setFavoritesOnly] = useState(false);
  const pathname = usePathname();
  const { user, favoriteSiteIds } = useAuth();

  const sitesById = useMemo(() => new Map(sites.map((s) => [s.site_id, s])), [sites]);

  const counts = useMemo(() => {
    const c: Record<FilterValue, number> = {
      all: sites.length,
      elevated_risk: 0,
      normal: 0,
      insufficient_evidence: 0,
    };
    for (const site of sites) {
      const status = riskBySiteId[site.site_id]?.status;
      if (status) c[status]++;
    }
    return c;
  }, [sites, riskBySiteId]);

  const filteredSiteIds = orderedSiteIds.filter((siteId) => {
    const site = sitesById.get(siteId);
    if (!site) return false;
    const matchesSearch =
      search.trim() === "" ||
      site.name.toLowerCase().includes(search.toLowerCase()) ||
      site.site_id.toLowerCase().includes(search.toLowerCase());
    const status = riskBySiteId[siteId]?.status;
    const matchesFilter = filter === "all" || status === filter;
    const matchesFavorites = !favoritesOnly || favoriteSiteIds.has(siteId);
    return matchesSearch && matchesFilter && matchesFavorites;
  });

  return (
    <>
      {isOpenMobile && (
        <div
          className="fixed inset-0 z-20 bg-black/40 md:hidden"
          onClick={onClose}
          aria-hidden
        />
      )}
      <aside
        className={`
          fixed inset-y-0 left-0 z-30 w-72 shrink-0 border-r border-border-color bg-surface-muted
          flex flex-col transition-transform md:static md:translate-x-0 md:z-auto
          ${isOpenMobile ? "translate-x-0" : "-translate-x-full"}
        `}
      >
        <div className="p-4 border-b border-border-color flex items-center justify-between md:hidden">
          <span className="text-sm font-semibold">Sites</span>
          <button onClick={onClose} className="text-muted-foreground hover:text-foreground text-sm">
            Close
          </button>
        </div>

        {/* The header shows the toggles from lg up; below that they live here. */}
        <div className="p-4 border-b border-border-color lg:hidden">
          <ScenarioToggles scenario={scenario} options={scenarioOptions} stacked />
        </div>

        <div className="p-4 flex flex-col gap-3 border-b border-border-color">
          <input
            type="search"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search sites..."
            className="w-full rounded-lg border border-border-color bg-surface px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-accent"
          />
          <div className="flex flex-col gap-1.5">
            {FILTERS.map((f) => (
              <button
                key={f.value}
                onClick={() => setFilter(f.value)}
                className={`flex items-center justify-between rounded-lg px-3 py-1.5 text-sm transition-colors ${
                  filter === f.value
                    ? "bg-accent text-accent-foreground font-medium"
                    : "text-foreground hover:bg-surface"
                }`}
              >
                <span>{f.label}</span>
                <span
                  className={`text-xs rounded-full px-1.5 ${
                    filter === f.value ? "bg-black/15" : "bg-border-color/60"
                  }`}
                >
                  {counts[f.value]}
                </span>
              </button>
            ))}
          </div>
          {user && (
            <button
              onClick={() => setFavoritesOnly((v) => !v)}
              className={`flex items-center justify-between rounded-lg px-3 py-1.5 text-sm transition-colors border ${
                favoritesOnly
                  ? "bg-rose-100 dark:bg-rose-500/15 border-rose-300 dark:border-rose-500/30 text-rose-700 dark:text-rose-300 font-medium"
                  : "border-border-color text-foreground hover:bg-surface"
              }`}
            >
              <span>&hearts; My favorites</span>
              <span
                className={`text-xs rounded-full px-1.5 ${
                  favoritesOnly ? "bg-black/10" : "bg-border-color/60"
                }`}
              >
                {favoriteSiteIds.size}
              </span>
            </button>
          )}
        </div>

        <nav className="flex-1 overflow-y-auto py-2">
          {filteredSiteIds.length === 0 && (
            <p className="px-4 py-6 text-sm text-muted-foreground text-center">No sites match.</p>
          )}
          {filteredSiteIds.map((siteId) => {
            const site = sitesById.get(siteId)!;
            const risk = riskBySiteId[siteId];
            const isActive = pathname === `/site/${siteId}`;
            return (
              <Link
                key={siteId}
                href={`/site/${siteId}`}
                onClick={onClose}
                className={`flex items-center justify-between gap-2 px-4 py-2.5 text-sm transition-colors border-l-2 ${
                  isActive
                    ? "border-accent bg-surface text-foreground font-medium"
                    : "border-transparent text-muted-foreground hover:bg-surface hover:text-foreground"
                }`}
              >
                <span className="truncate">{site.name}</span>
                {risk && (
                  <span
                    className="h-2 w-2 rounded-full shrink-0"
                    style={{ backgroundColor: statusDotColor(risk.status) }}
                  />
                )}
              </Link>
            );
          })}
        </nav>

        <div className="p-4 border-t border-border-color hidden md:block">
          <Link href="/" className="text-sm text-accent hover:underline">
            &larr; Overview
          </Link>
        </div>
      </aside>
    </>
  );
}
