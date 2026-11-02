import { describe, expect, it } from "vitest";
import { badgeArah, gridKomoditas, kartu, ringkasan, sparkline, type RenderCtx } from "../../src/lib/render";
import { keCsv } from "../../src/lib/duck";
import { ringkasPeta, tabelPeta } from "../../src/lib/peta";
import type { Komoditas, PasarWilayah, PetaBaris, Terkini } from "../../src/lib/types";

const kom = (id: `com_${number}` | `cat_${number}`, nama: string, level: 1 | 2): Komoditas => ({
  id,
  nama,
  tipe: level === 1 ? "kategori" : "komoditas",
  level,
  kategori_id: "cat_1",
  satuan: "kg",
  urutan: 1,
  het: null,
});

const ctx: RenderCtx = {
  base: "/PIHPS/",
  komoditas: new Map([
    ["cat_1", kom("cat_1", "Beras", 1)],
    ["com_1", kom("com_1", "Beras <Bawah>", 2)],
    ["com_2", kom("com_2", "Beras Medium", 2)],
  ]),
  kategori: [{ id: "cat_1", nama: "Beras", urutan: 1, komoditas: ["com_1", "com_2"] }],
  isNasional: false,
};

const t = (over: Partial<Terkini> = {}): Terkini => ({
  komoditas_id: "com_1",
  tanggal: "2026-10-30",
  harga: 16450,
  tanggal_sebelumnya: "2026-10-29",
  harga_sebelumnya: 16400,
  harga_7h: 16000,
  harga_30h: 15800,
  harga_1th: 15000,
  perubahan_pct_sebelumnya: 0.3,
  perubahan_pct_7h: 2.81,
  perubahan_pct_30h: 4.1,
  perubahan_pct_1th: 9.67,
  arah_7h: "naik",
  selisih_pct_nasional: 12.4,
  is_aktif: true,
  ...over,
});

describe("sparkline", () => {
  it("memutus garis pada null dan butuh minimal 2 titik", () => {
    const svg = sparkline([1, 2, null, 4, 5]).value;
    expect(svg.match(/M/g)?.length).toBe(3); // 2 segmen + titik akhir
    expect(sparkline([null, 3]).value).toBe("");
  });
});

describe("kartu", () => {
  it("menampilkan harga, arah dengan kata, tautan komoditas, dan escape nama", () => {
    const out = kartu(t(), [1, 2, 3], ctx).value;
    expect(out).toContain('href="/PIHPS/komoditas/com_1/"');
    expect(out).toContain("Rp16.450");
    expect(out).toContain("Naik 2,8%");
    expect(out).toContain("12,4% di atas rata-rata nasional");
    expect(out).toContain("Beras &lt;Bawah&gt;");
    expect(out).toContain('data-arah="naik"');
  });

  it("menandai data lama dan tanpa pembanding", () => {
    const out = kartu(t({ is_aktif: false, arah_7h: null, perubahan_pct_7h: null, tanggal: "2026-08-12" }), [], ctx).value;
    expect(out).toContain("kartu--lama");
    expect(out).toContain("Data terakhir 12 Agu 2026");
    expect(badgeArah(t({ arah_7h: null })).value).toContain("Belum ada pembanding");
    expect(badgeArah(t({ arah_7h: "tetap", perubahan_pct_7h: 0.2 })).value).toContain("Stabil");
  });
});

describe("grid & ringkasan", () => {
  const pasar: PasarWilayah = {
    jenis_pasar_id: 1,
    terkini: [t(), t({ komoditas_id: "com_2", arah_7h: "turun", perubahan_pct_7h: -1 }), t({ komoditas_id: "cat_1" })],
    harian: { tanggal: ["2026-10-29", "2026-10-30"], harga: { com_1: [1, 2], com_2: [2, 1] } },
    bulanan: { bulan: [], harga: {} },
  };
  it("hanya menghitung komoditas level 2 yang aktif", () => {
    expect(ringkasan(pasar, ctx)).toEqual({ naik: 1, turun: 1, tetap: 0, total: 2 });
  });
  it("mengelompokkan per kategori sesuai urutan", () => {
    const out = gridKomoditas(pasar, ctx).value;
    expect(out.indexOf("com_1")).toBeLessThan(out.indexOf("com_2"));
    expect(out).toContain('id="kat-cat_1"');
  });
});

describe("peta & csv", () => {
  const rows: PetaBaris[] = [
    { kode_wilayah: "prov-13", kode_bps: "31", nama: "DKI Jakarta", tanggal: "2026-10-30", harga: 20000, perubahan_pct_7h: 1, selisih_pct_nasional: 10, is_aktif: true },
    { kode_wilayah: "prov-14", kode_bps: "33", nama: "Jawa Tengah", tanggal: "2026-10-30", harga: 16000, perubahan_pct_7h: -1, selisih_pct_nasional: -5, is_aktif: true },
    { kode_wilayah: "prov-33", kode_bps: "94", nama: "Papua", tanggal: "2026-06-01", harga: 9000, perubahan_pct_7h: null, selisih_pct_nasional: null, is_aktif: false },
  ];
  it("mengurutkan dari termurah dan mengabaikan data tidak aktif", () => {
    expect(ringkasPeta(rows)).toBe("Termurah Jawa Tengah (Rp16.000), termahal DKI Jakarta (Rp20.000), selisih 25,0%.");
    const tbl = tabelPeta(rows, "/").value;
    expect(tbl.indexOf("Jawa Tengah")).toBeLessThan(tbl.indexOf("DKI Jakarta"));
    expect(tbl).not.toContain("Papua");
  });
  it("CSV meng-escape koma, kutip, dan baris baru", () => {
    const csv = keCsv({
      kolom: [{ nama: "nama", tipe: "Utf8" }, { nama: "harga", tipe: "Int64" }],
      baris: [["Beras, \"premium\"", 1], ["a\nb", null]],
      total: 2,
      ms: 1,
    });
    expect(csv).toBe('nama,harga\n"Beras, ""premium""",1\n"a\nb",');
  });
});
