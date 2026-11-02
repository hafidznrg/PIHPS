// DuckDB-WASM untuk halaman Jelajahi: memuat mesin, mendaftarkan view atas Parquet marts
// yang disajikan dari origin situs (dibaca lewat HTTP range, bukan diunduh utuh).
import * as duckdb from "@duckdb/duckdb-wasm";

export interface Sumber {
  base: string; // URL absolut ke /data/marts/
  fakta: string[]; // path relatif file Parquet fct_harga_harian (per partisi tahun)
  lokal: boolean; // true: bundle dari /duckdb/ (tes/offline), false: jsDelivr
}

export const VIEWS: Record<string, string> = {
  harga: "fakta harga harian (tanggal × jenis pasar × wilayah × komoditas)",
  wilayah: "dimensi wilayah SCD2 (nasional, provinsi, kab/kota, kode BPS)",
  komoditas: "kategori & komoditas (+HET bila ada)",
  pasar: "4 jenis pasar",
  tanggal: "kalender (hari kerja, libur, ada data PIHPS)",
};

function bundles(lokal: boolean, base: string): duckdb.DuckDBBundles {
  if (!lokal) return duckdb.getJsDelivrBundles();
  const u = (f: string) => new URL(`${base}duckdb/${f}`, location.href).href;
  return {
    mvp: { mainModule: u("duckdb-mvp.wasm"), mainWorker: u("duckdb-browser-mvp.worker.js") },
    eh: { mainModule: u("duckdb-eh.wasm"), mainWorker: u("duckdb-browser-eh.worker.js") },
  };
}

export async function buka(sumber: Sumber, siteBase: string): Promise<duckdb.AsyncDuckDBConnection> {
  const bundle = await duckdb.selectBundle(bundles(sumber.lokal, siteBase));
  // Worker lintas-origin (CDN) harus lewat blob yang meng-importScripts URL aslinya.
  const workerUrl = URL.createObjectURL(
    new Blob([`importScripts("${bundle.mainWorker}");`], { type: "text/javascript" }),
  );
  const db = new duckdb.AsyncDuckDB(new duckdb.VoidLogger(), new Worker(workerUrl));
  await db.instantiate(bundle.mainModule, bundle.pthreadWorker);
  URL.revokeObjectURL(workerUrl);
  const con = await db.connect();
  // Parquet adalah ekstensi yang diunduh dari extensions.duckdb.org (versi sesuai mesin).
  // Muat eksplisit di awal supaya kegagalan jaringan memberi pesan yang jelas.
  try {
    await con.query("load parquet");
  } catch (err) {
    throw new Error(
      "Ekstensi Parquet DuckDB gagal dimuat dari extensions.duckdb.org. Periksa koneksi internet " +
        `atau pemblokir konten, lalu coba lagi. (${err instanceof Error ? err.message : String(err)})`,
    );
  }
  const martsBase = new URL(sumber.base, location.href);
  const url = (p: string) => new URL(p, martsBase).href;
  const list = sumber.fakta.map((p) => `'${url(p)}'`).join(", ");
  await con.query(`
    create view harga as select * from read_parquet([${list}], hive_partitioning = true);
    create view wilayah as select * from read_parquet('${url("dim_wilayah.parquet")}');
    create view komoditas as select * from read_parquet('${url("dim_komoditas.parquet")}');
    create view pasar as select * from read_parquet('${url("dim_pasar.parquet")}');
    create view tanggal as select * from read_parquet('${url("dim_tanggal.parquet")}');
  `);
  return con;
}

export interface Hasil {
  kolom: { nama: string; tipe: string }[];
  baris: unknown[][];
  total: number;
  ms: number;
}

/** Jalankan kueri; nilai BigInt/Date diubah ke tipe JS yang bisa ditampilkan. */
export async function jalankan(con: duckdb.AsyncDuckDBConnection, sql: string, batas = 1000): Promise<Hasil> {
  const t0 = performance.now();
  const tabel = await con.query(sql);
  const ms = performance.now() - t0;
  const kolom = tabel.schema.fields.map((f) => ({ nama: f.name, tipe: String(f.type) }));
  const baris: unknown[][] = [];
  const n = Math.min(tabel.numRows, batas);
  for (let i = 0; i < n; i++) {
    const row = tabel.get(i);
    baris.push(kolom.map((k) => normal(row?.[k.nama], k.tipe)));
  }
  return { kolom, baris, total: tabel.numRows, ms };
}

function normal(v: unknown, tipe: string): unknown {
  if (v == null) return null;
  if (typeof v === "bigint") return Number(v);
  if (tipe.startsWith("Date")) return new Date(Number(v)).toISOString().slice(0, 10);
  if (tipe.startsWith("Timestamp")) return new Date(Number(v)).toISOString().replace("T", " ").slice(0, 19);
  if (typeof v === "object" && "toJSON" in (v as object)) return (v as { toJSON(): unknown }).toJSON();
  return v;
}

export function keCsv(h: Hasil): string {
  const esc = (v: unknown) => {
    const s = v == null ? "" : String(v);
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  return [h.kolom.map((k) => esc(k.nama)).join(","), ...h.baris.map((r) => r.map(esc).join(","))].join("\n");
}
