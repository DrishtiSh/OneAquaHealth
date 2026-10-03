import Link from "next/link";
import type { Site } from "@/lib/types";

interface RiverChainProps {
  orderedSiteIds: string[];
  sitesById: Map<string, Site>;
  currentSiteId?: string;
}

export default function RiverChain({ orderedSiteIds, sitesById, currentSiteId }: RiverChainProps) {
  return (
    <div className="w-full overflow-x-auto">
      <div className="flex items-center gap-1.5 min-w-max py-1">
        <span className="text-xs font-medium text-muted-foreground mr-1 uppercase tracking-wide">
          Head
        </span>
        {orderedSiteIds.map((siteId, i) => {
          const site = sitesById.get(siteId);
          const isCurrent = siteId === currentSiteId;
          return (
            <div key={siteId} className="flex items-center gap-1.5">
              <Link
                href={`/site/${siteId}`}
                className={`flex flex-col items-center px-2.5 py-1.5 rounded-lg border text-xs transition-colors ${
                  isCurrent
                    ? "bg-accent border-accent text-accent-foreground shadow-sm"
                    : "bg-surface border-border-color text-muted-foreground hover:border-accent hover:text-accent"
                }`}
              >
                <span className="font-semibold">{siteId}</span>
                <span className="text-[10px] opacity-80">{site?.name ?? ""}</span>
              </Link>
              {i < orderedSiteIds.length - 1 && <span className="text-muted-foreground/60">&rarr;</span>}
            </div>
          );
        })}
        <span className="text-xs font-medium text-muted-foreground ml-1 uppercase tracking-wide">
          Mouth
        </span>
      </div>
    </div>
  );
}
