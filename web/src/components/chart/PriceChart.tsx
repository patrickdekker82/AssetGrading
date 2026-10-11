"use client";

import {
  CandlestickSeries,
  type CandlestickData,
  createChart,
  createSeriesMarkers,
  CrosshairMode,
  HistogramSeries,
  type IChartApi,
  type ISeriesApi,
  LineSeries,
  LineStyle,
  type MouseEventParams,
  PriceScaleMode,
  type SeriesType,
  type Time,
} from "lightweight-charts";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Term } from "../Term";
import { type LinePoint, TrendLine } from "./trendline";

type Point = { time: string; value: number };
type IndicatorDef = { id: string; label_nl: string; pane: string; group: string; color: string; available: boolean;
  default_on: boolean };
export type ChartData = {
  interval: string;
  candles: { time: string; open: number; high: number; low: number; close: number }[];
  volume: Point[];
  indicators: Record<string, Point[]>;
  catalog: IndicatorDef[];
  benchmark: Point[] | null;
  benchmark_name: string | null;
  markers: { time: string; text: string }[];
  gate_zones: { start: string; end: string; labels: string[] }[];
  tradingview_symbol: string;
};

const INTERVALS = [{ id: "1d", label: "Dag" }, { id: "1w", label: "Week" }, { id: "1M", label: "Maand" }];
const MAX_PANES = 2;
const STORE_KEY = "graadmeter.chart.crypto.indicators";
const euro = new Intl.NumberFormat("nl-NL", { maximumSignificantDigits: 6 });

function readStore<T>(key: string, fallback: T): T {
  try {
    const raw = window.localStorage.getItem(key);
    return raw ? (JSON.parse(raw) as T) : fallback;
  } catch {
    return fallback;
  }
}

function writeStore(key: string, value: unknown) {
  try {
    window.localStorage.setItem(key, JSON.stringify(value));
  } catch {
    // storage unavailable (private window): settings simply are not remembered
  }
}

function cssVar(name: string, fallback: string): string {
  if (typeof window === "undefined") return fallback;
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback;
}

export function PriceChart({ assetId }: { assetId: string }) {
  const [interval, setChartInterval] = useState("1d");
  const [data, setData] = useState<ChartData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [logScale, setLogScale] = useState(false);
  const [compare, setCompare] = useState(false);
  const [enabled, setEnabled] = useState<string[] | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [drawing, setDrawing] = useState(false);
  const [lines, setLines] = useState<[LinePoint, LinePoint][]>([]);
  const [showTv, setShowTv] = useState(false);
  const legendRef = useRef<HTMLDivElement>(null);
  const container = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const pending = useRef<LinePoint | null>(null);
  const linesKey = `graadmeter.chart.lines.${assetId}`;

  useEffect(() => {
    setLines(readStore<[LinePoint, LinePoint][]>(linesKey, []));
  }, [linesKey]);

  useEffect(() => {
    let cancelled = false;
    setError(null);
    fetch(`/api/assets/${assetId}/chart?interval=${interval}`)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then((d: ChartData) => {
        if (cancelled) return;
        setData(d);
        setEnabled((current) => current ?? readStore<string[]>(STORE_KEY,
          d.catalog.filter((c) => c.default_on).map((c) => c.id)));
      })
      .catch(() => !cancelled && setError("De grafiekdata kon niet worden geladen."));
    return () => { cancelled = true; };
  }, [assetId, interval]);

  const active = useMemo(() => {
    if (!data || !enabled) return [];
    return data.catalog.filter((c) => c.available && enabled.includes(c.id));
  }, [data, enabled]);

  const toggleIndicator = useCallback((def: IndicatorDef) => {
    setMessage(null);
    setEnabled((current) => {
      const list = current ?? [];
      if (list.includes(def.id)) {
        const next = list.filter((x) => x !== def.id);
        writeStore(STORE_KEY, next);
        return next;
      }
      if (def.pane !== "price" && data) {
        const panes = new Set(data.catalog.filter((c) => list.includes(c.id) && c.pane !== "price").map((c) => c.pane));
        panes.add(def.pane);
        if (panes.size > MAX_PANES) {
          setMessage(`Maximaal ${MAX_PANES} indicatorvensters tegelijk. Zet er eerst één uit.`);
          return list;
        }
      }
      const next = [...list, def.id];
      writeStore(STORE_KEY, next);
      return next;
    });
  }, [data]);

  // (Re)build the chart whenever data or settings change; rebuilding is fast for daily data.
  useEffect(() => {
    if (!container.current || !data || data.candles.length === 0 || showTv) return;
    const text = cssVar("--text", "#16191f");
    const border = cssVar("--border", "#e2e5ea");
    const chart = createChart(container.current, {
      autoSize: true,
      layout: { background: { color: "transparent" }, textColor: text, attributionLogo: true,
        panes: { separatorColor: border } },
      grid: { vertLines: { color: border }, horzLines: { color: border } },
      // Leave the bottom fifth of the price pane to the volume bars.
      rightPriceScale: { borderColor: border, mode: logScale ? PriceScaleMode.Logarithmic : PriceScaleMode.Normal,
        scaleMargins: { top: 0.08, bottom: 0.22 } },
      timeScale: { borderColor: border },
      crosshair: { mode: CrosshairMode.Normal },
      localization: { locale: "nl-NL", priceFormatter: (p: number) => euro.format(p) },
    });
    chartRef.current = chart;

    // Gate zones: shaded background on days where a hard rule limited the grade.
    if (data.gate_zones.length) {
      const zones = chart.addSeries(HistogramSeries, {
        priceScaleId: "zones", color: "rgba(207, 34, 46, 0.12)", priceLineVisible: false, lastValueVisible: false,
      }, 0);
      zones.priceScale().applyOptions({ scaleMargins: { top: 0, bottom: 0 } });
      zones.setData(data.candles.filter((c) => data.gate_zones.some((z) => c.time >= z.start && c.time <= z.end))
        .map((c) => ({ time: c.time as Time, value: 1 })));
    }

    const candles = chart.addSeries(CandlestickSeries, {
      upColor: "#1a7f37", downColor: "#cf222e", borderVisible: false, wickUpColor: "#1a7f37", wickDownColor: "#cf222e",
    });
    candles.setData(data.candles.map((c) => ({ ...c, time: c.time as Time })) as CandlestickData<Time>[]);
    candleRef.current = candles;

    const volume = chart.addSeries(HistogramSeries, {
      priceScaleId: "volume", color: "rgba(100, 116, 139, 0.35)", priceLineVisible: false, lastValueVisible: false,
      priceFormat: { type: "volume" },
    }, 0);
    volume.priceScale().applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
    volume.setData(data.volume.map((v) => ({ time: v.time as Time, value: v.value })));

    const lineSeries: { def: IndicatorDef; series: ISeriesApi<SeriesType> }[] = [];
    const paneOrder = [...new Set(active.filter((a) => a.pane !== "price").map((a) => a.pane))];
    for (const def of active) {
      const paneIndex = def.pane === "price" ? 0 : paneOrder.indexOf(def.pane) + 1;
      const series = chart.addSeries(LineSeries, {
        color: def.color, lineWidth: def.pane === "price" ? 1 : 2, priceLineVisible: false, lastValueVisible: false,
        crosshairMarkerVisible: false, title: "",
        ...(def.pane === "price" ? {} : { priceFormat: { type: "price", precision: 4, minMove: 0.0001 } }),
      }, paneIndex);
      series.setData((data.indicators[def.id] ?? []).map((p) => ({ time: p.time as Time, value: p.value })));
      lineSeries.push({ def, series });
    }
    chart.panes().forEach((pane, i) => pane.setStretchFactor(i === 0 ? 3 : 1));

    if (compare && data.benchmark) {
      const bench = chart.addSeries(LineSeries, {
        color: "#8250df", lineWidth: 1, lineStyle: LineStyle.Dashed, priceLineVisible: false, lastValueVisible: false,
      }, 0);
      bench.setData(data.benchmark.map((p) => ({ time: p.time as Time, value: p.value })));
    }

    if (data.markers.length) {
      createSeriesMarkers(candles, data.markers.map((m) => ({
        time: m.time as Time, position: "aboveBar" as const, color: "#1f6feb", shape: "arrowDown" as const, text: m.text,
      })));
    }

    for (const [a, b] of lines) candles.attachPrimitive(new TrendLine(a, b));

    // The legend is written straight into the DOM: a React state update per mouse move would re-render
    // the whole component and make panning stutter on slow machines.
    const setLegend = (value: string) => {
      if (legendRef.current) legendRef.current.textContent = value || "\u00a0";
    };
    const onMove = (param: MouseEventParams<Time>) => {
      if (!param.time) {
        setLegend("");
        return;
      }
      const c = param.seriesData.get(candles) as CandlestickData<Time> | undefined;
      const parts = [String(param.time)];
      if (c) parts.push(`O ${euro.format(c.open)} H ${euro.format(c.high)} L ${euro.format(c.low)} S ${euro.format(c.close)}`);
      for (const { def, series } of lineSeries) {
        const v = param.seriesData.get(series) as { value?: number } | undefined;
        if (v?.value !== undefined) parts.push(`${def.label_nl} ${v.value.toLocaleString("nl-NL", { maximumSignificantDigits: 5 })}`);
      }
      setLegend(parts.join(" · "));
    };
    chart.subscribeCrosshairMove(onMove);
    // Daily view starts with the last two years (fewer bars to draw on slow machines); scroll for more.
    const bars = data.candles.length;
    if (data.interval === "1d" && bars > 730) {
      chart.timeScale().setVisibleLogicalRange({ from: bars - 730, to: bars + 5 });
    } else {
      chart.timeScale().fitContent();
    }
    return () => {
      chart.unsubscribeCrosshairMove(onMove);
      chart.remove();
      chartRef.current = null;
      candleRef.current = null;
    };
  }, [data, active, logScale, compare, lines, showTv]);

  // Drawing: two clicks set the two ends of a trend line.
  useEffect(() => {
    const chart = chartRef.current;
    if (!chart || !drawing) return;
    const onClick = (param: MouseEventParams<Time>) => {
      const series = candleRef.current;
      if (!param.time || !param.point || !series) return;
      const price = series.coordinateToPrice(param.point.y);
      if (price === null) return;
      const point = { time: param.time, price };
      if (!pending.current) {
        pending.current = point;
        setMessage("Klik op het tweede punt van de lijn.");
        return;
      }
      const next: [LinePoint, LinePoint][] = [...lines, [pending.current, point]];
      pending.current = null;
      setLines(next);
      writeStore(linesKey, next);
      setDrawing(false);
      setMessage(null);
    };
    chart.subscribeClick(onClick);
    return () => chart.unsubscribeClick(onClick);
  }, [drawing, lines, linesKey, data, active]);

  if (error) return <p className="notice">{error}</p>;

  return (
    <div className="chart-block">
      <div className="toolbar chart-toolbar">
        <div className="segmented" role="tablist" aria-label="Tijdschaal">
          {INTERVALS.map((i) => (
            <button key={i.id} className={i.id === interval ? "seg active" : "seg"} onClick={() => setChartInterval(i.id)}
              aria-selected={i.id === interval} role="tab">{i.label}</button>
          ))}
        </div>
        <label className="check"><input type="checkbox" checked={logScale} onChange={(e) => setLogScale(e.target.checked)} />
          Log-schaal</label>
        {data?.benchmark && (
          <label className="check"><input type="checkbox" checked={compare} onChange={(e) => setCompare(e.target.checked)} />
            Vergelijk met {data.benchmark_name}</label>
        )}
        <button className={drawing ? "button active" : "button"} onClick={() => { pending.current = null; setDrawing(!drawing);
          setMessage(drawing ? null : "Klik op het eerste punt van de lijn."); }}>
          {drawing ? "Tekenen stoppen" : "Trendlijn tekenen"}
        </button>
        {lines.length > 0 && (
          <button className="button" onClick={() => { setLines([]); writeStore(linesKey, []); }}>Lijnen wissen</button>
        )}
        <button className={showTv ? "button active" : "button"} onClick={() => setShowTv(!showTv)}>
          {showTv ? "Eigen grafiek" : "Tweede mening (TradingView)"}
        </button>
      </div>
      {data && !showTv && (
        <div className="indicator-bar">
          {(["score", "context"] as const).map((group) => (
            <div key={group} className="indicator-group">
              <span className="muted small">{group === "score" ? "In de score" : "Context"}</span>
              {data.catalog.filter((c) => c.group === group).map((c) => (
                <button key={c.id} disabled={!c.available} title={c.available ? undefined : "Geen data"}
                  className={enabled?.includes(c.id) ? "chip-toggle on" : "chip-toggle"} onClick={() => toggleIndicator(c)}
                  style={{ borderColor: enabled?.includes(c.id) ? c.color : undefined }}>
                  <span className="dot" style={{ background: c.color }} />{c.label_nl}
                </button>
              ))}
            </div>
          ))}
        </div>
      )}
      {message && <p className="muted small chart-message">{message}</p>}
      {showTv ? (
        <TradingViewWidget symbol={data?.tradingview_symbol ?? ""} />
      ) : (
        <>
          <div ref={legendRef} className="chart-legend small">{"\u00a0"}</div>
          <div ref={container} className="chart" aria-label="Koersgrafiek" />
          {data && data.gate_zones.length > 0 && (
            <p className="muted small">Rood gearceerd: dagen waarop een <Term id="gate">gate</Term> de grade begrensde.</p>
          )}
        </>
      )}
    </div>
  );
}

function TradingViewWidget({ symbol }: { symbol: string }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!ref.current || !symbol) return;
    ref.current.innerHTML = "";
    const script = document.createElement("script");
    script.src = "https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js";
    script.async = true;
    script.innerHTML = JSON.stringify({ symbol, interval: "D", locale: "nl_NL", autosize: true, allow_symbol_change: true });
    ref.current.appendChild(script);
  }, [symbol]);
  return (
    <div>
      <p className="muted small">
        Gratis widget van TradingView: alleen TradingView-data, vaak vertraagd, zonder de eigen grades. Deze tab laadt
        pas als je hem opent.
      </p>
      <div ref={ref} className="chart tradingview-widget-container" />
    </div>
  );
}
