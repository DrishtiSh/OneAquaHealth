"use client";

import { useState } from "react";
import AppHeader from "@/components/AppHeader";
import Sidebar from "@/components/Sidebar";
import type { Scenario, ScenarioOptions, Site, SiteRiskSummary } from "@/lib/types";

interface AppShellProps {
  sites: Site[];
  orderedSiteIds: string[];
  riskBySiteId: Record<string, SiteRiskSummary>;
  scenario: Scenario;
  scenarioOptions: ScenarioOptions;
  footer: React.ReactNode;
  children: React.ReactNode;
}

export default function AppShell({
  sites,
  orderedSiteIds,
  riskBySiteId,
  scenario,
  scenarioOptions,
  footer,
  children,
}: AppShellProps) {
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false);

  return (
    <div className="flex min-h-screen flex-col">
      <AppHeader
        onMenuClick={() => setMobileSidebarOpen((v) => !v)}
        scenario={scenario}
        scenarioOptions={scenarioOptions}
      />
      <div className="flex flex-1 min-h-0">
        <Sidebar
          sites={sites}
          orderedSiteIds={orderedSiteIds}
          riskBySiteId={riskBySiteId}
          scenario={scenario}
          scenarioOptions={scenarioOptions}
          isOpenMobile={mobileSidebarOpen}
          onClose={() => setMobileSidebarOpen(false)}
        />
        <div className="flex-1 min-w-0 overflow-y-auto flex flex-col">
          <div className="flex-1">{children}</div>
          {footer}
        </div>
      </div>
    </div>
  );
}
