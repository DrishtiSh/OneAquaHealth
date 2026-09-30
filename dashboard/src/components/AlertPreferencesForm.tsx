"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useAuth } from "@/lib/auth-context";
import type { Site } from "@/lib/types";

interface Preference {
  siteId: string;
  notifyOnElevatedRisk: boolean;
  notifyOnAnyChange: boolean;
}

export default function AlertPreferencesForm({ sites }: { sites: Site[] }) {
  const { user, loading: authLoading } = useAuth();
  const [prefs, setPrefs] = useState<Record<string, Preference>>({});
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    if (!user) return;
    let cancelled = false;
    (async () => {
      const res = await fetch("/api/alert-preferences");
      if (res.ok && !cancelled) {
        const data = await res.json();
        const map: Record<string, Preference> = {};
        for (const p of data.preferences as Preference[]) map[p.siteId] = p;
        setPrefs(map);
      }
      if (!cancelled) setLoaded(true);
    })();
    return () => {
      cancelled = true;
    };
  }, [user]);

  async function updatePref(siteId: string, patch: Partial<Preference>) {
    const current = prefs[siteId] ?? {
      siteId,
      notifyOnElevatedRisk: false,
      notifyOnAnyChange: false,
    };
    const next = { ...current, ...patch };
    setPrefs((p) => ({ ...p, [siteId]: next }));
    await fetch("/api/alert-preferences", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        siteId,
        notifyOnElevatedRisk: next.notifyOnElevatedRisk,
        notifyOnAnyChange: next.notifyOnAnyChange,
      }),
    });
  }

  if (authLoading) return null;

  if (!user) {
    return (
      <div className="rounded-xl border border-border-color bg-surface shadow-sm p-6 text-center">
        <p className="text-sm text-muted-foreground">
          <Link href="/login" className="text-accent hover:underline">
            Sign in
          </Link>{" "}
          to set alert preferences.
        </p>
      </div>
    );
  }

  if (!loaded) {
    return <p className="text-sm text-muted-foreground">Loading&hellip;</p>;
  }

  return (
    <div className="rounded-xl border border-border-color bg-surface shadow-sm divide-y divide-border-color overflow-hidden">
      {sites.map((site) => {
        const pref = prefs[site.site_id];
        return (
          <div
            key={site.site_id}
            className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 sm:gap-4 px-4 py-3"
          >
            <div>
              <p className="text-sm font-medium text-foreground">{site.name}</p>
              <p className="text-xs text-muted-foreground">{site.site_id}</p>
            </div>
            <div className="flex items-center gap-4 text-sm text-foreground">
              <label className="flex items-center gap-1.5">
                <input
                  type="checkbox"
                  checked={pref?.notifyOnElevatedRisk ?? false}
                  onChange={(e) =>
                    void updatePref(site.site_id, { notifyOnElevatedRisk: e.target.checked })
                  }
                  className="accent-accent"
                />
                Elevated risk
              </label>
              <label className="flex items-center gap-1.5">
                <input
                  type="checkbox"
                  checked={pref?.notifyOnAnyChange ?? false}
                  onChange={(e) =>
                    void updatePref(site.site_id, { notifyOnAnyChange: e.target.checked })
                  }
                  className="accent-accent"
                />
                Any change
              </label>
            </div>
          </div>
        );
      })}
    </div>
  );
}
