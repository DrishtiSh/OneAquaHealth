"use client";

import dynamic from "next/dynamic";
import type { Site, SiteRiskSummary } from "@/lib/types";

// Leaflet touches `window` at import time, so the map must never render on
// the server -- ssr:false only works from inside a Client Component.
const SiteMap = dynamic(() => import("@/components/SiteMap"), {
  ssr: false,
  loading: () => (
    <div className="flex h-full w-full items-center justify-center text-sm text-muted-foreground">
      Loading map&hellip;
    </div>
  ),
});

export default function SiteMapLoader(props: {
  sites: Site[];
  riskBySiteId: Record<string, SiteRiskSummary>;
}) {
  return <SiteMap {...props} />;
}
