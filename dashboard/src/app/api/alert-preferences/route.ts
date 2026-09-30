import { NextResponse } from "next/server";
import { requireUserId } from "@/lib/require-user";
import db from "@/lib/db";

interface AlertPreferenceRow {
  site_id: string;
  notify_on_elevated_risk: number;
  notify_on_any_change: number;
}

// UI + storage only: nothing currently sends a real notification, since
// Stages 5-9 (model/detectors/API) that would trigger one don't exist yet.
// This lets the preference live somewhere real, ready to be read once they do.

export async function GET() {
  const result = await requireUserId();
  if ("error" in result) return result.error;

  const rows = db
    .prepare(
      "SELECT site_id, notify_on_elevated_risk, notify_on_any_change FROM alert_preferences WHERE user_id = ?"
    )
    .all(result.userId) as AlertPreferenceRow[];

  return NextResponse.json({
    preferences: rows.map((r) => ({
      siteId: r.site_id,
      notifyOnElevatedRisk: Boolean(r.notify_on_elevated_risk),
      notifyOnAnyChange: Boolean(r.notify_on_any_change),
    })),
  });
}

export async function POST(request: Request) {
  const result = await requireUserId();
  if ("error" in result) return result.error;

  const body = await request.json().catch(() => null);
  const siteId = typeof body?.siteId === "string" ? body.siteId : "";
  const notifyOnElevatedRisk = Boolean(body?.notifyOnElevatedRisk);
  const notifyOnAnyChange = Boolean(body?.notifyOnAnyChange);
  if (!siteId) return NextResponse.json({ error: "Missing siteId." }, { status: 400 });

  if (!notifyOnElevatedRisk && !notifyOnAnyChange) {
    db.prepare("DELETE FROM alert_preferences WHERE user_id = ? AND site_id = ?").run(
      result.userId,
      siteId
    );
    return NextResponse.json({ ok: true });
  }

  db.prepare(
    `INSERT INTO alert_preferences (user_id, site_id, notify_on_elevated_risk, notify_on_any_change, updated_at)
     VALUES (?, ?, ?, ?, datetime('now'))
     ON CONFLICT (user_id, site_id) DO UPDATE SET
       notify_on_elevated_risk = excluded.notify_on_elevated_risk,
       notify_on_any_change = excluded.notify_on_any_change,
       updated_at = excluded.updated_at`
  ).run(result.userId, siteId, notifyOnElevatedRisk ? 1 : 0, notifyOnAnyChange ? 1 : 0);

  return NextResponse.json({ ok: true });
}
