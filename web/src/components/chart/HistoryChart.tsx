"use client";

import { createChart, createSeriesMarkers, LineSeries, type Time } from "lightweight-charts";
import { useEffect, useRef } from "react";

export type HistoryPoint = { as_of: string; score: number | null; letter: string | null; status: string };

/** Score over time with a marker where the published letter changed. */
export function HistoryChart({ points }: { points: HistoryPoint[] }) {
  const ref = useRef<HTMLDivElement>(null);
  const scored = points.filter((p) => p.score !== null);

  useEffect(() => {
    if (!ref.current || scored.length < 2) return;
    const style = getComputedStyle(document.documentElement);
    const chart = createChart(ref.current, {
      autoSize: true,
      layout: { background: { color: "transparent" }, textColor: style.getPropertyValue("--text").trim(),
        attributionLogo: true },
      grid: { vertLines: { visible: false }, horzLines: { color: style.getPropertyValue("--border").trim() } },
      rightPriceScale: { autoScale: false },
    });
    const line = chart.addSeries(LineSeries, { color: "#1f6feb", lineWidth: 2 });
    line.setData(scored.map((p) => ({ time: p.as_of as Time, value: p.score! })));
    chart.priceScale("right").applyOptions({ autoScale: false });
    line.applyOptions({ autoscaleInfoProvider: () => ({ priceRange: { minValue: 0, maxValue: 100 } }) });
    const markers = [];
    for (let i = 1; i < points.length; i++) {
      if (points[i].letter !== points[i - 1].letter) {
        markers.push({ time: points[i].as_of as Time, position: "aboveBar" as const, color: "#8250df",
          shape: "circle" as const, text: points[i].letter ?? "–" });
      }
    }
    createSeriesMarkers(line, markers);
    chart.timeScale().fitContent();
    return () => chart.remove();
  }, [points, scored]);

  if (scored.length < 2) {
    const first = points[0]?.as_of;
    return (
      <p className="muted">
        De geschiedenis bouwt zich op: er is {points.length === 1 ? "één beoordeling" : `${points.length} beoordelingen`}
        {first ? ` (sinds ${first})` : ""}. Na een paar nachtruns verschijnt hier het verloop van score en grade.
      </p>
    );
  }
  return <div ref={ref} className="history-chart" aria-label="Verloop van de score" />;
}
