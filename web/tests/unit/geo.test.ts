import { describe, expect, it } from "vitest";
import { pathRelatif, petaSvg, sederhanakan } from "../../src/lib/geo";

describe("peta SVG build-time", () => {
  const svg = petaSvg();
  it("34 provinsi dengan path dan rasio bentuk yang benar (tidak direntang)", () => {
    expect(svg.provinsi).toHaveLength(34);
    for (const p of svg.provinsi) expect(p.d.length, p.nama).toBeGreaterThan(20);
    // Indonesia ±46° x 17° -> rasio ±2,7; peta lama direntang mengikuti kotak wadah
    expect(svg.w / svg.h).toBeGreaterThan(2.5);
    expect(svg.w / svg.h).toBeLessThan(2.9);
  });
  it("titik jangkar label berada di dalam kanvas", () => {
    for (const p of svg.provinsi) {
      expect(p.cx).toBeGreaterThan(0);
      expect(p.cx).toBeLessThan(svg.w);
      expect(p.cy).toBeGreaterThan(0);
      expect(p.cy).toBeLessThan(svg.h);
    }
    const jatim = svg.provinsi.find((p) => p.kode_bps === "35")!;
    const papua = svg.provinsi.find((p) => p.kode_bps === "94")!;
    expect(papua.cx).toBeGreaterThan(jatim.cx);
  });
  it("ringkas: total path di bawah 40 KB", () => {
    expect(svg.provinsi.reduce((n, p) => n + p.d.length, 0)).toBeLessThan(40_000);
  });
  it("Douglas-Peucker membuang titik segaris, path relatif membuang titik kembar", () => {
    expect(sederhanakan([[0, 0], [1, 0.01], [2, 0], [3, 0], [4, 0], [4, 4], [0, 0]], 0.1)).toEqual([[0, 0], [4, 0], [4, 4], [0, 0]]);
    expect(pathRelatif([[0, 0], [10, 0], [10, 0.2], [10, 10], [0, 0]])).toBe("M0 0l10 0 0 10z");
  });
});
