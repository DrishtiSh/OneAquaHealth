import { NextResponse } from "next/server";
import { auth } from "@/auth";

/** Shared guard for API routes that require a signed-in user. */
export async function requireUserId(): Promise<{ userId: string } | { error: NextResponse }> {
  const session = await auth();
  if (!session?.user?.id) {
    return { error: NextResponse.json({ error: "Not signed in." }, { status: 401 }) };
  }
  return { userId: session.user.id };
}
