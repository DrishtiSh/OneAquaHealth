export default function MockDataBanner() {
  return (
    <div className="flex items-start gap-3 rounded-xl border border-amber-300/60 bg-amber-100 dark:bg-amber-500/10 dark:border-amber-500/30 px-4 py-3 text-sm text-amber-900 dark:text-amber-200">
      <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-amber-400 text-xs font-bold text-white">
        !
      </span>
      <p>
        <span className="font-semibold">Placeholder risk data.</span> Scores and findings shown
        below are mock values for UI development &mdash; the model/detector backend isn&apos;t
        connected yet. Site locations, rainfall, the river chain, and exposure points are real.
      </p>
    </div>
  );
}
