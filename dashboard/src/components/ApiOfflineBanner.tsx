import { API_URL } from "@/lib/api";

// Shown whenever a reader fell back to bundled data because the Insight API wasn't reachable.
export default function ApiOfflineBanner() {
  return (
    <div className="flex items-start gap-3 rounded-xl border border-amber-300/60 bg-amber-100 dark:bg-amber-500/10 dark:border-amber-500/30 px-4 py-3 text-sm text-amber-900 dark:text-amber-200">
      <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-amber-400 text-xs font-bold text-white">
        !
      </span>
      <p>
        <span className="font-semibold">Insight API not reachable at {API_URL}.</span> Risk scores
        and findings below are placeholder values. Site locations, rainfall, the river chain and
        exposure points come from bundled pipeline exports. Start the API with{" "}
        <code className="font-mono text-xs">cd api &amp;&amp; npm start</code> (or{" "}
        <code className="font-mono text-xs">npm run dev</code> from the repo root) and reload.
      </p>
    </div>
  );
}
