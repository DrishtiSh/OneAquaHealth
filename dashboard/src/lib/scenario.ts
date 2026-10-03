// The dashboard's scenario toggles (rain assumption, detection sensitivity) live in cookies, not
// search params, so the root layout's sidebar and map can follow them too.

import { cache } from "react";
import { cookies } from "next/headers";
import { getScenarioOptions } from "@/lib/data";
import type { Scenario } from "@/lib/types";

export const VARIANT_COOKIE = "oah_variant";
export const SENSITIVITY_COOKIE = "oah_sensitivity";

/** The current request's scenario; unknown cookie values fall back to the snapshot's defaults. */
export const getScenario = cache(async (): Promise<Scenario> => {
  const [store, options] = await Promise.all([cookies(), getScenarioOptions()]);
  const variant = store.get(VARIANT_COOKIE)?.value;
  const sensitivity = store.get(SENSITIVITY_COOKIE)?.value;
  return {
    variant: options.variants.some((v) => v.id === variant) ? variant! : options.default_variant,
    sensitivity: options.sensitivity_levels.some((s) => s.id === sensitivity)
      ? sensitivity!
      : options.default_sensitivity,
  };
});
