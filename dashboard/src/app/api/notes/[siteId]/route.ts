import { NextResponse } from "next/server";
import { requireUserId } from "@/lib/require-user";
import db from "@/lib/db";

const MAX_NOTE_LENGTH = 1000;

export async function GET(_request: Request, ctx: RouteContext<"/api/notes/[siteId]">) {
  const result = await requireUserId();
  if ("error" in result) return result.error;

  const { siteId } = await ctx.params;
  const row = db
    .prepare("SELECT note, updated_at FROM site_notes WHERE user_id = ? AND site_id = ?")
    .get(result.userId, siteId) as { note: string; updated_at: string } | undefined;

  return NextResponse.json({ note: row?.note ?? "", updatedAt: row?.updated_at ?? null });
}

export async function PUT(request: Request, ctx: RouteContext<"/api/notes/[siteId]">) {
  const result = await requireUserId();
  if ("error" in result) return result.error;

  const { siteId } = await ctx.params;
  const body = await request.json().catch(() => null);
  const note = typeof body?.note === "string" ? body.note.slice(0, MAX_NOTE_LENGTH) : "";

  if (note.trim() === "") {
    db.prepare("DELETE FROM site_notes WHERE user_id = ? AND site_id = ?").run(
      result.userId,
      siteId
    );
    return NextResponse.json({ note: "" });
  }

  db.prepare(
    `INSERT INTO site_notes (user_id, site_id, note, updated_at)
     VALUES (?, ?, ?, datetime('now'))
     ON CONFLICT (user_id, site_id) DO UPDATE SET note = excluded.note, updated_at = excluded.updated_at`
  ).run(result.userId, siteId, note);

  return NextResponse.json({ note });
}
