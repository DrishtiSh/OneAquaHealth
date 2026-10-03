"use client";

import "leaflet/dist/leaflet.css";
import { MapContainer, TileLayer, CircleMarker, Popup } from "react-leaflet";
import Link from "next/link";
import { statusDotColor } from "@/components/StatusBadge";
import type { Site, SiteRiskSummary } from "@/lib/types";

// react-leaflet's default marker icon paths break with bundlers; using
// CircleMarker (colored dots) instead avoids needing an icon-path fix.

interface SiteMapProps {
  sites: Site[];
  // A plain Record, not a Map -- Map instances aren't serializable across
  // the Server -> Client Component boundary.
  riskBySiteId: Record<string, SiteRiskSummary>;
}

export default function SiteMap({ sites, riskBySiteId }: SiteMapProps) {
  const center: [number, number] = [
    sites.reduce((sum, s) => sum + s.lat, 0) / sites.length,
    sites.reduce((sum, s) => sum + s.lon, 0) / sites.length,
  ];

  return (
    <MapContainer
      center={center}
      zoom={15}
      scrollWheelZoom={false}
      style={{ height: "100%", width: "100%" }}
    >
      <TileLayer
        className="map-tiles"
        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
        url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
      />
      {sites.map((site) => {
        const risk = riskBySiteId[site.site_id];
        const color = risk ? statusDotColor(risk.status) : "#94a3b8";
        return (
          <CircleMarker
            key={site.site_id}
            center={[site.lat, site.lon]}
            radius={9}
            pathOptions={{ color: "#ffffff", weight: 2, fillColor: color, fillOpacity: 0.95 }}
          >
            <Popup>
              <div className="text-sm min-w-40">
                <p className="font-semibold text-foreground">{site.name}</p>
                <p className="text-xs text-muted-foreground mb-1.5">{site.site_id}</p>
                {risk && (
                  <p className="mb-1.5">
                    <span
                      className="inline-block h-2 w-2 rounded-full mr-1.5"
                      style={{ backgroundColor: color }}
                    />
                    <span className="font-medium capitalize">{risk.status.replace("_", " ")}</span>
                  </p>
                )}
                <Link href={`/site/${site.site_id}`} className="text-accent font-medium hover:underline">
                  View details &rarr;
                </Link>
              </div>
            </Popup>
          </CircleMarker>
        );
      })}
    </MapContainer>
  );
}
