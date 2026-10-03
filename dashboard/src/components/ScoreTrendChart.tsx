"use client";

import {
  Area,
  CartesianGrid,
  ComposedChart,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { formatMonth, formatWeek, likelihoodLabel } from "@/lib/format";
import type { TimeseriesWeek } from "@/lib/types";

// Two small multiples sharing one week axis (synced crosshair): W and H are different questions
// (higher W is better, higher H is worse), so they get a panel each rather than one crowded plot.
// Each panel: the 90% interval as a band, the median as a line. Detected changes are marked on W,
// because the change detector is defined on drops in W.

interface Point {
  week: string;
  wBand: [number, number];
  wMid: number;
  hBand: [number, number];
  hMid: number;
  confirmed: number | null;
  possible: number | null;
  src: TimeseriesWeek;
}

const AXIS_TICK = { fontSize: 10, fill: "var(--muted-foreground)" };

export default function ScoreTrendChart({ weeks }: { weeks: TimeseriesWeek[] }) {
  const data: Point[] = weeks.map((w) => ({
    week: w.week_start,
    wBand: [w.W.q05, w.W.q95],
    wMid: w.W.q50,
    hBand: [w.H.q05, w.H.q95],
    hMid: w.H.q50,
    confirmed: w.alert_level === "confirmed" ? w.W.q50 : null,
    possible: w.alert_level === "possible" ? w.W.q50 : null,
    src: w,
  }));
  const nConfirmed = data.filter((d) => d.confirmed != null).length;
  const nPossible = data.filter((d) => d.possible != null).length;

  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
        <span>Line: weekly estimate &middot; band: 90% interval</span>
        <span className="flex items-center gap-1.5">
          <svg width="10" height="10" aria-hidden>
            <circle cx="5" cy="5" r="4" fill="var(--alert-confirmed)" />
          </svg>
          Confirmed change ({nConfirmed})
        </span>
        <span className="flex items-center gap-1.5">
          <svg width="10" height="10" aria-hidden>
            <circle cx="5" cy="5" r="3.5" fill="var(--surface)" stroke="var(--alert-possible)" strokeWidth="2" />
          </svg>
          Possible change ({nPossible})
        </span>
      </div>

      <Panel
        title="Water quality (W) — higher is cleaner"
        data={data}
        band="wBand"
        mid="wMid"
        color="var(--series-w)"
        markers
      />
      <Panel
        title="Health risk (H) — higher is riskier"
        data={data}
        band="hBand"
        mid="hMid"
        color="var(--series-h)"
        showXAxis
      />

      <details className="text-xs">
        <summary className="cursor-pointer text-muted-foreground hover:text-foreground w-fit">
          Show as table
        </summary>
        <div className="mt-2 max-h-64 overflow-y-auto rounded-lg border border-border-color">
          <table className="w-full text-left">
            <thead className="sticky top-0 bg-surface-muted text-muted-foreground">
              <tr>
                <th className="px-2 py-1 font-medium">Week</th>
                <th className="px-2 py-1 font-medium">W (90%)</th>
                <th className="px-2 py-1 font-medium">H (90%)</th>
                <th className="px-2 py-1 font-medium">Reports</th>
                <th className="px-2 py-1 font-medium">Evidence</th>
                <th className="px-2 py-1 font-medium">Change</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border-color text-foreground">
              {[...weeks].reverse().map((w) => (
                <tr key={w.week_start}>
                  <td className="px-2 py-1 whitespace-nowrap">{w.week_start}</td>
                  <td className="px-2 py-1 whitespace-nowrap">{fmtBand(w.W)}</td>
                  <td className="px-2 py-1 whitespace-nowrap">{fmtBand(w.H)}</td>
                  <td className="px-2 py-1">{w.n_reports}</td>
                  <td className="px-2 py-1">{w.evidence}</td>
                  <td className="px-2 py-1">{w.alert_level && w.alert_level !== "none" ? w.alert_level : ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </div>
  );
}

function fmtBand(b: { q05: number; q50: number; q95: number }) {
  return `${b.q50.toFixed(0)} (${b.q05.toFixed(0)}–${b.q95.toFixed(0)})`;
}

function Panel({
  title,
  data,
  band,
  mid,
  color,
  markers = false,
  showXAxis = false,
}: {
  title: string;
  data: Point[];
  band: "wBand" | "hBand";
  mid: "wMid" | "hMid";
  color: string;
  markers?: boolean;
  showXAxis?: boolean;
}) {
  return (
    <div>
      <p className="text-xs font-medium text-foreground mb-1">{title}</p>
      <ResponsiveContainer width="100%" height={showXAxis ? 170 : 150}>
        <ComposedChart data={data} syncId="site-trend" margin={{ top: 6, right: 12, left: -16, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--border-color)" vertical={false} />
          <XAxis
            dataKey="week"
            hide={!showXAxis}
            tick={AXIS_TICK}
            tickFormatter={formatMonth}
            interval={Math.max(0, Math.ceil(data.length / 8) - 1)}
            axisLine={{ stroke: "var(--border-color)" }}
            tickLine={false}
          />
          <YAxis domain={[0, 100]} ticks={[0, 50, 100]} tick={AXIS_TICK} axisLine={false} tickLine={false} />
          <Tooltip content={<TrendTooltip />} cursor={{ stroke: "var(--muted-foreground)", strokeDasharray: "3 3" }} />
          <Area
            dataKey={band}
            stroke="none"
            fill={color}
            fillOpacity={0.18}
            isAnimationActive={false}
            activeDot={false}
          />
          <Line dataKey={mid} stroke={color} strokeWidth={2} dot={false} isAnimationActive={false} activeDot={{ r: 4 }} />
          {markers && (
            <Line
              dataKey="possible"
              stroke="none"
              isAnimationActive={false}
              dot={{ r: 4, fill: "var(--surface)", stroke: "var(--alert-possible)", strokeWidth: 2 }}
              activeDot={false}
              legendType="none"
            />
          )}
          {markers && (
            <Line
              dataKey="confirmed"
              stroke="none"
              isAnimationActive={false}
              dot={{ r: 4, fill: "var(--alert-confirmed)", stroke: "var(--surface)", strokeWidth: 2 }}
              activeDot={false}
              legendType="none"
            />
          )}
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}

function TrendTooltip({ active, payload }: { active?: boolean; payload?: { payload: Point }[] }) {
  if (!active || !payload?.length) return null;
  const w = payload[0].payload.src;
  const alert = w.alert_level && w.alert_level !== "none" ? w.alert_level : null;
  return (
    <div className="rounded-lg border border-border-color bg-surface px-3 py-2 text-xs text-foreground shadow-md">
      <p className="font-medium mb-1">Week of {formatWeek(w.week_start)}</p>
      <p>Water quality {fmtBand(w.W)}</p>
      <p>Health risk {fmtBand(w.H)}</p>
      <p className="text-muted-foreground mt-1">
        {w.n_reports} report{w.n_reports === 1 ? "" : "s"} &middot; evidence {w.evidence}
        {w.mixing_flag ? " · reports disagree" : ""}
      </p>
      {w.p_change != null && (
        <p className="text-muted-foreground">
          Drop in W: {likelihoodLabel(w.p_change)} (p {w.p_change.toFixed(2)})
          {alert ? ` — ${alert} change` : ""}
        </p>
      )}
      {w.weekly_rainfall_mm != null && (
        <p className="text-muted-foreground">
          Rain {w.weekly_rainfall_mm.toFixed(1)} mm{w.heavy_rain_week ? " (heavy)" : ""}
        </p>
      )}
    </div>
  );
}
