import { NextResponse } from "next/server";
import { requireUserId } from "@/lib/require-user";
import db from "@/lib/db";

export async function GET() {
  const result = await requireUserId();
  if ("error" in result) return result.error;

  const rows = db
    .prepare("SELECT site_id FROM favorite_sites WHERE user_id = ?")
    .all(result.userId) as { site_id: string }[];
  return NextResponse.json({ siteIds: rows.map((r) => r.site_id) });
}

export async function POST(request: Request) {
  const result = await requireUserId();
  if ("error" in result) return result.error;

  const body = await request.json().catch(() => null);
  const siteId = typeof body?.siteId === "string" ? body.siteId : "";
  if (!siteId) return NextResponse.json({ error: "Missing siteId." }, { status: 400 });

  db.prepare("INSERT OR IGNORE INTO favorite_sites (user_id, site_id) VALUES (?, ?)").run(
    result.userId,
    siteId
  );
  return NextResponse.json({ ok: true });
}
