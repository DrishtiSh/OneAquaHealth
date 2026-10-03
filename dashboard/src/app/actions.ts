"use server";

import { cookies } from "next/headers";
import { SENSITIVITY_COOKIE, VARIANT_COOKIE } from "@/lib/scenario";

const ONE_YEAR = 60 * 60 * 24 * 365;
// Only the shape is checked here; getScenario() validates the value against the loaded snapshot.
const TOKEN_RE = /^[A-Za-z0-9_-]{1,32}$/;

/** Store one scenario toggle. Called from ScenarioToggles; the page re-renders with the new value. */
export async function setScenarioToggle(name: "variant" | "sensitivity", value: string) {
  if (!TOKEN_RE.test(value)) return;
  const store = await cookies();
  store.set(name === "variant" ? VARIANT_COOKIE : SENSITIVITY_COOKIE, value, {
    path: "/",
    maxAge: ONE_YEAR,
    sameSite: "lax",
  });
}
