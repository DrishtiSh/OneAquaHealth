import { NextResponse } from "next/server";
import { requireUserId } from "@/lib/require-user";
import db from "@/lib/db";

export async function DELETE(_request: Request, ctx: RouteContext<"/api/favorites/[siteId]">) {
  const result = await requireUserId();
  if ("error" in result) return result.error;

  const { siteId } = await ctx.params;
  db.prepare("DELETE FROM favorite_sites WHERE user_id = ? AND site_id = ?").run(
    result.userId,
    siteId
  );
  return NextResponse.json({ ok: true });
}
