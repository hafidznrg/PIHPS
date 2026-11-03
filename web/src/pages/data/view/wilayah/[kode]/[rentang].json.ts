// File "view" untuk grafik wilayah, dibuat saat build dari kontrak serving (tanpa mengubah
// kontrak/pipeline). Peramban hanya mengunduh rentang yang dipilih (harian ±90 hari atau
// bulanan) untuk komoditas level 2 — bukan seluruh wilayah/<kode>.json.
import type { APIRoute, GetStaticPaths } from "astro";
import { getMeta, getWilayah } from "../../../../../lib/data";

export const getStaticPaths = (() =>
  getMeta().wilayah.flatMap((w) => (["harian", "bulanan"] as const).map((rentang) => ({ params: { kode: w.kode, rentang } })))) satisfies GetStaticPaths;

export const GET: APIRoute = ({ params }) => {
  const meta = getMeta();
  const ids = meta.komoditas.filter((k) => k.level === 2).map((k) => k.id);
  const doc = getWilayah(params["kode"]!);
  const harian = params["rentang"] === "harian";
  const pasar = doc.pasar.map((p) => {
    const s = harian ? p.harian : p.bulanan;
    const harga: Record<string, (number | null)[]> = {};
    for (const id of ids) {
      const v = s.harga[id];
      if (v?.some((x) => x != null)) harga[id] = v;
    }
    return { id: p.jenis_pasar_id, x: harian ? p.harian.tanggal : p.bulanan.bulan, harga };
  });
  return new Response(JSON.stringify({ tanggal_acuan: doc.tanggal_acuan, pasar }), {
    headers: { "Content-Type": "application/json; charset=utf-8" },
  });
};
