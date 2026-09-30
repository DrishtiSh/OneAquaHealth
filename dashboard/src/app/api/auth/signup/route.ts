import { NextResponse } from "next/server";
import {
  createUser,
  findUserByEmail,
  hashPassword,
  isValidEmail,
  isValidPassword,
} from "@/lib/auth";

// Only creates the account row. The client signs the user in immediately
// afterward via Auth.js's signIn("credentials", ...) -- see auth-context.tsx
// -- so there's exactly one place (src/auth.ts) that issues session cookies.
export async function POST(request: Request) {
  const body = await request.json().catch(() => null);
  const email = typeof body?.email === "string" ? body.email.trim().toLowerCase() : "";
  const password = typeof body?.password === "string" ? body.password : "";
  const displayName = typeof body?.displayName === "string" ? body.displayName.trim() : "";

  if (!isValidEmail(email)) {
    return NextResponse.json({ error: "Enter a valid email address." }, { status: 400 });
  }
  if (!isValidPassword(password)) {
    return NextResponse.json({ error: "Password must be at least 8 characters." }, { status: 400 });
  }
  if (!displayName || displayName.length > 50) {
    return NextResponse.json({ error: "Enter a name (up to 50 characters)." }, { status: 400 });
  }
  if (findUserByEmail(email)) {
    return NextResponse.json({ error: "An account with that email already exists." }, { status: 409 });
  }

  const passwordHash = await hashPassword(password);
  createUser(email, passwordHash, displayName, "credentials");

  return NextResponse.json({ ok: true });
}
