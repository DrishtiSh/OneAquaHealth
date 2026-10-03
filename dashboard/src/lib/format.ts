// Display helpers shared by Server and Client Components.

// Spelled out rather than Intl: Node and browsers disagree on short month names ("Sep" vs
// "Sept"), which would make server and client renders differ.
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** "2026-09-14" -> "14 Sep 2026" (the same style the pipeline's findings use). */
export function formatWeek(iso: string): string {
  const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
  return `${d} ${MONTHS[m - 1]} ${y}`;
}

/** "2026-09-14" -> "Sep 2026", for chart axes. */
export function formatMonth(iso: string): string {
  const [y, m] = iso.slice(0, 10).split("-").map(Number);
  return `${MONTHS[m - 1]} ${y}`;
}

/** Probability -> the wording the findings use (pipeline/common/config.py VERBAL_PROBABILITY). */
export function likelihoodLabel(p: number): string {
  if (p >= 0.9) return "very likely";
  if (p >= 0.66) return "likely";
  if (p >= 0.33) return "possibly";
  return "unlikely";
}
