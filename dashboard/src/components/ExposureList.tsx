import type { ExposureFeature } from "@/lib/types";

const CATEGORY_META: Record<string, { label: string; icon: string }> = {
  playground: { label: "Playground", icon: "🛝" },
  school: { label: "School", icon: "🏫" },
  park: { label: "Park", icon: "🌳" },
};

export default function ExposureList({ items }: { items: ExposureFeature[] }) {
  if (items.length === 0) {
    return <p className="text-sm text-muted-foreground">No exposure data available.</p>;
  }

  return (
    <ul className="divide-y divide-border-color">
      {items.map((item) => {
        const meta = CATEGORY_META[item.category] ?? { label: item.category, icon: "📍" };
        return (
          <li key={item.category} className="flex items-center justify-between gap-3 py-2.5 text-sm">
            <div className="flex items-center gap-2.5 min-w-0">
              <span className="text-lg leading-none">{meta.icon}</span>
              <div className="min-w-0">
                <p className="font-medium text-foreground">{meta.label}</p>
                {item.nearest_poi_name && item.nearest_poi_name !== "unnamed" && (
                  <p className="text-xs text-muted-foreground truncate">{item.nearest_poi_name}</p>
                )}
              </div>
            </div>
            <div className="text-right shrink-0">
              {item.data_source === "unavailable" ? (
                <span className="text-muted-foreground italic text-xs">unknown</span>
              ) : item.nearest_poi_distance_m === null ? (
                <span className="text-muted-foreground text-xs">none nearby</span>
              ) : (
                <span
                  className={
                    item.is_exposure_relevant
                      ? "text-rose-600 dark:text-rose-400 font-semibold"
                      : "text-foreground"
                  }
                >
                  {Math.round(item.nearest_poi_distance_m)}m
                </span>
              )}
            </div>
          </li>
        );
      })}
    </ul>
  );
}
