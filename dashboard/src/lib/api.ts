// Server-side client for the Stage 9 Insight API (api/). Only Server Components call it, so the
// browser never talks to the API directly and CORS never comes into play.

import type { ApiEnvelope } from "@/lib/types";

export const API_URL = (process.env.OAH_API_URL || "http://localhost:4000").replace(/\/+$/, "");
const API_PREFIX = "/api/v1";
const TIMEOUT_MS = 3000;
// After an outage, skip the API for this long so pages don't each wait on a failing request.
const RETRY_AFTER_MS = 5000;

/** The API could not be reached, or answered with an error. */
export class ApiUnavailable extends Error {
  constructor(
    message: string,
    readonly status?: number,
  ) {
    super(message);
  }
}

// Process-wide health, so an outage is logged once (not once per reader per request).
const health: { online: boolean | null; downUntil: number } = { online: null, downUntil: 0 };

function markDown(reason: string): ApiUnavailable {
  if (health.online !== false) {
    console.warn(
      `[api] Insight API offline at ${API_URL}: ${reason}. Serving bundled fallback data. ` +
        "Start it with: npm --prefix api start (or npm run dev from the repo root)",
    );
  }
  health.online = false;
  health.downUntil = Date.now() + RETRY_AFTER_MS;
  return new ApiUnavailable(`Insight API not reachable at ${API_URL}: ${reason}`);
}

function markUp(snapshotId: string | undefined) {
  if (health.online === false) {
    console.info(`[api] Insight API back online at ${API_URL}${snapshotId ? ` (snapshot ${snapshotId})` : ""}`);
  }
  health.online = true;
}

type Query = Record<string, string | number | boolean | undefined>;

export async function apiGet<T>(path: string, query: Query = {}): Promise<ApiEnvelope<T>> {
  if (health.online === false && Date.now() < health.downUntil) {
    throw new ApiUnavailable(`Insight API not reachable at ${API_URL} (retrying shortly)`);
  }

  const url = new URL(`${API_URL}${API_PREFIX}${path}`);
  for (const [k, v] of Object.entries(query)) {
    if (v !== undefined) url.searchParams.set(k, String(v));
  }

  let res: Response;
  try {
    // The snapshot can hot-reload under the API, so never serve a stale copy from Next's cache.
    res = await fetch(url, { cache: "no-store", signal: AbortSignal.timeout(TIMEOUT_MS) });
  } catch (err) {
    const cause = (err as { cause?: { code?: string } }).cause?.code;
    throw markDown(cause ?? (err as Error).message);
  }
  if (!res.ok) {
    const body = (await res.json().catch(() => null)) as { error?: { message?: string } } | null;
    const message = body?.error?.message ?? `GET ${url.pathname} returned ${res.status}`;
    // A 5xx (e.g. 503 "no snapshot is loaded") is an outage; a 4xx is a real answer.
    if (res.status >= 500) throw markDown(message);
    markUp(undefined);
    throw new ApiUnavailable(message, res.status);
  }
  const envelope = (await res.json()) as ApiEnvelope<T>;
  markUp(envelope.snapshot?.id);
  return envelope;
}
