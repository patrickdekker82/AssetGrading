// Trend line drawing tool, after the trend-line plugin in the official Lightweight Charts examples.
import type { CanvasRenderingTarget2D } from "fancy-canvas";
import type {
  IChartApi,
  IPrimitivePaneRenderer,
  IPrimitivePaneView,
  ISeriesApi,
  ISeriesPrimitive,
  SeriesAttachedParameter,
  SeriesType,
  Time,
} from "lightweight-charts";

export type LinePoint = { time: Time; price: number };
type Coord = { x: number | null; y: number | null };

class TrendLineRenderer implements IPrimitivePaneRenderer {
  constructor(private readonly p1: Coord, private readonly p2: Coord, private readonly color: string) {}

  draw(target: CanvasRenderingTarget2D) {
    const { p1, p2 } = this;
    if (p1.x === null || p1.y === null || p2.x === null || p2.y === null) return;
    target.useBitmapCoordinateSpace((scope) => {
      const ctx = scope.context;
      const h = scope.horizontalPixelRatio;
      const v = scope.verticalPixelRatio;
      ctx.lineWidth = 2 * h;
      ctx.strokeStyle = this.color;
      ctx.beginPath();
      ctx.moveTo(p1.x! * h, p1.y! * v);
      ctx.lineTo(p2.x! * h, p2.y! * v);
      ctx.stroke();
      ctx.fillStyle = this.color;
      for (const p of [p1, p2]) {
        ctx.beginPath();
        ctx.arc(p.x! * h, p.y! * v, 3 * h, 0, 2 * Math.PI);
        ctx.fill();
      }
    });
  }
}

class TrendLineView implements IPrimitivePaneView {
  private a: Coord = { x: null, y: null };
  private b: Coord = { x: null, y: null };

  constructor(private readonly source: TrendLine) {}

  update() {
    const { chart, series, p1, p2 } = this.source;
    if (!chart || !series) return;
    const ts = chart.timeScale();
    this.a = { x: ts.timeToCoordinate(p1.time), y: series.priceToCoordinate(p1.price) };
    this.b = { x: ts.timeToCoordinate(p2.time), y: series.priceToCoordinate(p2.price) };
  }

  renderer() {
    return new TrendLineRenderer(this.a, this.b, this.source.color);
  }
}

export class TrendLine implements ISeriesPrimitive<Time> {
  chart: IChartApi | null = null;
  series: ISeriesApi<SeriesType> | null = null;
  private readonly views: TrendLineView[];

  constructor(readonly p1: LinePoint, readonly p2: LinePoint, readonly color = "#f57c00") {
    this.views = [new TrendLineView(this)];
  }

  attached(param: SeriesAttachedParameter<Time>) {
    this.chart = param.chart as IChartApi;
    this.series = param.series;
  }

  detached() {
    this.chart = null;
    this.series = null;
  }

  updateAllViews() {
    this.views.forEach((view) => view.update());
  }

  paneViews() {
    return this.views;
  }
}
