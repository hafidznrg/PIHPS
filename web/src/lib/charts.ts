// ECharts dengan impor modular (hanya chart & komponen yang dipakai) + tema dari CSS
// variables sehingga ikut mode terang/gelap.
import * as echarts from "echarts/core";
import { BarChart, LineChart, MapChart } from "echarts/charts";
import {
  DataZoomComponent,
  GridComponent,
  LegendComponent,
  TooltipComponent,
  VisualMapComponent,
  MarkLineComponent,
} from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";

echarts.use([
  LineChart,
  BarChart,
  MapChart,
  GridComponent,
  TooltipComponent,
  LegendComponent,
  DataZoomComponent,
  VisualMapComponent,
  MarkLineComponent,
  CanvasRenderer,
]);

export { echarts };

export function cssVar(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

/** Warna tetap per jenis pasar (1 tradisional, 2 modern, 3 pedagang besar, 4 produsen). */
export function warnaPasar(id: number | string): string {
  return cssVar(`--seri-${id}`);
}

export function palette(): string[] {
  return [1, 2, 3, 4].map((i) => cssVar(`--seri-${i}`));
}

export function baseOption(): echarts.EChartsCoreOption {
  const text = cssVar("--teks-redup");
  const line = cssVar("--garis");
  return {
    color: palette(),
    textStyle: { fontFamily: cssVar("--font"), color: text },
    grid: { left: 8, right: 16, top: 40, bottom: 56, containLabel: true },
    tooltip: {
      trigger: "axis",
      backgroundColor: cssVar("--permukaan"),
      borderColor: line,
      textStyle: { color: cssVar("--teks") },
      confine: true,
    },
    legend: { top: 0, textStyle: { color: text }, itemGap: 16 },
    xAxis: {
      axisLine: { lineStyle: { color: line } },
      axisLabel: { color: text, hideOverlap: true },
      splitLine: { show: false },
    },
    yAxis: {
      axisLabel: { color: text },
      splitLine: { lineStyle: { color: line, opacity: 0.6 } },
    },
  };
}

/** Inisialisasi chart pada elemen; ikut ukuran kontainer dan bisa dibuang. */
export function mount(el: HTMLElement): echarts.ECharts {
  const chart = echarts.getInstanceByDom(el) ?? echarts.init(el, undefined, { renderer: "canvas" });
  new ResizeObserver(() => chart.resize()).observe(el);
  return chart;
}

const idr = new Intl.NumberFormat("id-ID", { maximumFractionDigits: 0 });
export const rp = (v: unknown): string => (typeof v === "number" ? `Rp${idr.format(v)}` : "–");
export const rpRingkas = (v: number): string =>
  v >= 1000 ? `${idr.format(Math.round(v / 1000))}rb` : idr.format(v);
