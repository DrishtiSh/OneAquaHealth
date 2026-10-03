import Link from "next/link";
import type { Provenance } from "@/lib/data";
import { formatWeek } from "@/lib/format";

// Standing disclaimer plus which snapshot the numbers on screen came from.
export default function DataFooter({ provenance }: { provenance: Provenance }) {
  const { source, snapshot, disclaimer } = provenance;
  return (
    <footer className="border-t border-border-color px-6 py-4 text-xs text-muted-foreground flex flex-col sm:flex-row sm:items-center sm:justify-between gap-1">
      <p>
        {disclaimer}{" "}
        <Link href="/benchmark" className="text-accent hover:underline whitespace-nowrap">
          How accurate is this?
        </Link>
      </p>
      <p className="font-mono">
        {source === "api" && snapshot
          ? `snapshot ${snapshot.id} · data to week of ${formatWeek(snapshot.latest_week)}`
          : "Insight API offline · bundled data"}
      </p>
    </footer>
  );
}
