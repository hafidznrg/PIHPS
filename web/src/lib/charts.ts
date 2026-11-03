// ECharts dengan impor modular (hanya chart & komponen yang dipakai; peta = SVG build-time) + tema dari CSS
// variables sehingga ikut mode terang/gelap.
import * as echarts from "echarts/core";
import { BarChart, LineChart } from "echarts/charts";
import {
  DataZoomComponent,
  GridComponent,
  LegendComponent,
  TooltipComponent,
  MarkLineComponent,
} from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";

echarts.use([
  LineChart,
  BarChart,
  GridComponent,
  TooltipComponent,
  LegendComponent,
  DataZoomComponent,
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
  const font = cssVar("--font");
  const sempit = window.matchMedia("(max-width: 40rem)").matches;
  return {
    color: palette(),
    textStyle: { fontFamily: font, color: text, fontSize: 11 },
    // legenda dibungkus (bukan digulir "1/2") — di HP memakan dua baris, jadi grid turun
    grid: { left: 0, right: 8, top: sempit ? 62 : 40, bottom: 52, containLabel: true },
    tooltip: {
      trigger: "axis",
      backgroundColor: cssVar("--permukaan"),
      borderColor: cssVar("--garis-kuat"),
      borderWidth: 1,
      borderRadius: 2,
      padding: [8, 10],
      extraCssText: "box-shadow:none;",
      textStyle: { color: cssVar("--teks"), fontFamily: font, fontSize: 12 },
      axisPointer: { type: "line", lineStyle: { color: cssVar("--teks-redup"), width: 1, type: "dashed" } },
      confine: true,
    },
    legend: {
      type: "plain",
      top: 0,
      left: 0,
      right: 0,
      icon: "rect",
      itemWidth: 16,
      itemHeight: 3,
      itemGap: sempit ? 12 : 18,
      textStyle: { color: cssVar("--teks"), fontFamily: font, fontSize: 12 },
      inactiveColor: line,
    },
    xAxis: {
      axisLine: { lineStyle: { color: cssVar("--garis-kuat") } },
      axisTick: { show: false },
      axisLabel: { color: text, hideOverlap: true, margin: 10 },
      splitLine: { show: false },
    },
    yAxis: {
      position: "right",
      axisLabel: { color: text, fontFamily: cssVar("--font-angka"), fontSize: 10.5 },
      splitLine: { lineStyle: { color: line, type: [3, 3] } },
    },
  };
}

/** Gaya seri garis yang konsisten di semua grafik. */
export const gayaGaris = {
  type: "line" as const,
  showSymbol: false,
  symbol: "circle",
  symbolSize: 6,
  lineStyle: { width: 1.8 },
  emphasis: { focus: "series" as const, lineStyle: { width: 2.4 } },
  connectNulls: false,
};

/** dataZoom (geser/cubit + slider) yang mengikuti tema terang/gelap. */
export function zoom(start = 0): object[] {
  return [
    { type: "inside", start },
    {
      type: "slider",
      start,
      height: 20,
      bottom: 6,
      brushSelect: false,
      borderColor: cssVar("--garis"),
      backgroundColor: cssVar("--permukaan-2"),
      fillerColor: "rgba(127,127,127,0.14)",
      dataBackground: { lineStyle: { color: cssVar("--teks-redup") }, areaStyle: { color: cssVar("--garis") } },
      selectedDataBackground: { lineStyle: { color: cssVar("--aksen") }, areaStyle: { color: cssVar("--garis") } },
      handleStyle: { color: cssVar("--permukaan"), borderColor: cssVar("--teks-redup") },
      moveHandleStyle: { color: cssVar("--teks-redup") },
      textStyle: { color: cssVar("--teks-redup") },
    },
  ];
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
