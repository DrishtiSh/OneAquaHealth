"use client";

import { useState } from "react";
import AppHeader from "@/components/AppHeader";
import Sidebar from "@/components/Sidebar";
import type { Site, SiteRiskSummary } from "@/lib/types";

interface AppShellProps {
  sites: Site[];
  orderedSiteIds: string[];
  riskBySiteId: Record<string, SiteRiskSummary>;
  children: React.ReactNode;
}

export default function AppShell({ sites, orderedSiteIds, riskBySiteId, children }: AppShellProps) {
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false);

  return (
    <div className="flex min-h-screen flex-col">
      <AppHeader onMenuClick={() => setMobileSidebarOpen((v) => !v)} />
      <div className="flex flex-1 min-h-0">
        <Sidebar
          sites={sites}
          orderedSiteIds={orderedSiteIds}
          riskBySiteId={riskBySiteId}
          isOpenMobile={mobileSidebarOpen}
          onClose={() => setMobileSidebarOpen(false)}
        />
        <div className="flex-1 min-w-0 overflow-y-auto">{children}</div>
      </div>
    </div>
  );
}
