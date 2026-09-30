"use client";

import {
  ResponsiveContainer,
  ComposedChart,
  Bar,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
} from "recharts";
import type { WeatherWeek } from "@/lib/types";

interface RainfallChartProps {
  weeks: WeatherWeek[];
}

export default function RainfallChart({ weeks }: RainfallChartProps) {
  const chartData = weeks.map((w) => ({
    week: w.week_start.slice(0, 10),
    rainfall: w.weekly_rainfall_mm,
    heavy: w.heavy_rain_week ? w.weekly_rainfall_mm : null,
  }));

  return (
    <ResponsiveContainer width="100%" height={260}>
      <ComposedChart data={chartData} margin={{ top: 8, right: 16, left: 0, bottom: 8 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="var(--border-color)" vertical={false} />
        <XAxis
          dataKey="week"
          tick={{ fontSize: 10, fill: "var(--muted-foreground)" }}
          interval={Math.ceil(chartData.length / 10)}
          axisLine={{ stroke: "var(--border-color)" }}
          tickLine={false}
        />
        <YAxis
          tick={{ fontSize: 11, fill: "var(--muted-foreground)" }}
          label={{
            value: "mm",
            angle: -90,
            position: "insideLeft",
            fontSize: 11,
            fill: "var(--muted-foreground)",
          }}
          axisLine={false}
          tickLine={false}
        />
        <Tooltip
          contentStyle={{
            borderRadius: 8,
            border: "1px solid var(--border-color)",
            background: "var(--surface)",
            color: "var(--foreground)",
            fontSize: 12,
          }}
        />
        <Bar dataKey="rainfall" name="Weekly rainfall (mm)" fill="#2dd4bf" radius={[3, 3, 0, 0]} />
        <Line
          dataKey="heavy"
          name="Heavy rain week"
          stroke="#e11d48"
          strokeWidth={0}
          dot={{ r: 3, fill: "#e11d48" }}
          legendType="none"
        />
      </ComposedChart>
    </ResponsiveContainer>
  );
}
