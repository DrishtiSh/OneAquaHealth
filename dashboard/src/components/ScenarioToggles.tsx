"use client";

import { useTransition } from "react";
import { useRouter } from "next/navigation";
import { setScenarioToggle } from "@/app/actions";
import type { Scenario, ScenarioOptions } from "@/lib/types";

interface ScenarioTogglesProps {
  scenario: Scenario;
  options: ScenarioOptions;
  /** Stack the two controls (sidebar) instead of laying them out in a row (header). */
  stacked?: boolean;
}

// The rain-ablation model answers "what if we didn't assume rain matters?", so label it that way.
function variantLabel(v: ScenarioOptions["variants"][number]) {
  return v.rain_assumed ? "On" : "Off";
}

function sensitivityLabel(s: ScenarioOptions["sensitivity_levels"][number]) {
  return `${s.id.charAt(0).toUpperCase()}${s.id.slice(1)} (${s.delta_W})`;
}

export default function ScenarioToggles({ scenario, options, stacked = false }: ScenarioTogglesProps) {
  const router = useRouter();
  const [pending, startTransition] = useTransition();

  function change(name: "variant" | "sensitivity", value: string) {
    startTransition(async () => {
      await setScenarioToggle(name, value);
      router.refresh();
    });
  }

  return (
    <div
      className={`flex ${stacked ? "flex-col gap-2" : "items-center gap-4"} ${pending ? "opacity-60" : ""}`}
      aria-busy={pending}
    >
      <Segmented
        label="Rain assumption"
        title="Whether the model treats rain as a covariate. Off uses the rain-free model, which is how the rain-to-overflow pattern is tested without building it in."
        value={scenario.variant}
        items={options.variants.map((v) => ({ id: v.id, label: variantLabel(v), title: v.description }))}
        onChange={(v) => change("variant", v)}
      />
      <Segmented
        label="Sensitivity"
        title="Size of drop in the water-quality index (points) that counts as a change."
        value={scenario.sensitivity}
        items={options.sensitivity_levels.map((s) => ({
          id: s.id,
          label: sensitivityLabel(s),
          title: `Flag drops of more than ${s.delta_W} points`,
        }))}
        onChange={(v) => change("sensitivity", v)}
      />
    </div>
  );
}

function Segmented({
  label,
  title,
  value,
  items,
  onChange,
}: {
  label: string;
  title: string;
  value: string;
  items: { id: string; label: string; title: string }[];
  onChange: (id: string) => void;
}) {
  return (
    <div className="flex items-center gap-2" title={title}>
      <span className="text-xs text-muted-foreground whitespace-nowrap">{label}</span>
      <div role="radiogroup" aria-label={label} className="flex rounded-lg border border-border-color bg-surface p-0.5">
        {items.map((item) => {
          const active = item.id === value;
          return (
            <button
              key={item.id}
              type="button"
              role="radio"
              aria-checked={active}
              title={item.title}
              onClick={() => !active && onChange(item.id)}
              className={`rounded-md px-2 py-0.5 text-xs transition-colors whitespace-nowrap ${
                active
                  ? "bg-accent text-accent-foreground font-medium"
                  : "text-muted-foreground hover:text-foreground"
              }`}
            >
              {item.label}
            </button>
          );
        })}
      </div>
    </div>
  );
}
