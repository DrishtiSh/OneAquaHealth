import type { Observation } from "@/lib/types";

// Rubric scales from pipeline/common/schema.py: clarity 1 (clear) - 5 (murky), smell intensity
// 0-3, trash 0-4. Only the clarity endpoints have agreed words, so the rest stay numeric.
function clarity(n: number): string {
  if (n === 1) return "water clear";
  if (n === 5) return "water murky";
  return `clarity ${n}/5`;
}

function describe(o: Observation): string {
  const parts: string[] = [];
  if (o.water_clarity != null) parts.push(clarity(o.water_clarity));
  if (o.smell && o.smell !== "none") {
    const intensity = o.smell_intensity != null ? ` (${o.smell_intensity}/3)` : "";
    parts.push(`${o.smell.replace("_", " ")} smell${intensity}`);
  } else if (o.smell === "none") {
    parts.push("no smell");
  }
  if (o.trash_level != null) parts.push(`trash ${o.trash_level}/4`);
  if (o.insect_presence != null) parts.push(o.insect_presence ? "insects seen" : "no insects");
  return parts.join(" · ");
}

// The newest de-identified volunteer reports behind a site's scores.
export default function ObservationList({ observations, total }: { observations: Observation[]; total: number }) {
  if (observations.length === 0) {
    return <p className="text-sm text-muted-foreground">No citizen reports yet.</p>;
  }
  return (
    <div className="flex flex-col gap-2">
      <ul className="divide-y divide-border-color">
        {observations.map((o) => (
          <li key={o.observation_id} className="py-2 text-sm flex flex-col sm:flex-row sm:gap-4">
            <span className="text-muted-foreground font-mono text-xs shrink-0 sm:w-24 sm:pt-0.5">{o.observed_date}</span>
            <div className="min-w-0">
              <p className="text-foreground">{describe(o) || "No details recorded"}</p>
              {o.notes && <p className="text-xs text-muted-foreground italic">&ldquo;{o.notes}&rdquo;</p>}
            </div>
          </li>
        ))}
      </ul>
      <p className="text-xs text-muted-foreground">
        Showing the {observations.length} newest of {total} reports.
      </p>
    </div>
  );
}
