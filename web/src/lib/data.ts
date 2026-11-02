// Pemuat data saat build (Node). Data serving disalin ke public/data/serving sebelum build
// (`pihps.serving download` di CI, atau `pihps.serving demo` untuk lokal). Peramban memuat
// file yang sama lewat fetch dari /data/serving/... .
import { readFileSync } from "node:fs";
import { join } from "node:path";
import type { Komoditas, Meta, PetaDoc, TrenDoc, WilayahDoc } from "./types";

const DATA_DIR = process.env.PIHPS_DATA_DIR ?? join(process.cwd(), "public", "data");
const cache = new Map<string, unknown>();

function read<T>(rel: string): T {
  const hit = cache.get(rel);
  if (hit) return hit as T;
  const path = join(DATA_DIR, "serving", rel);
  let doc: T;
  try {
    doc = JSON.parse(readFileSync(path, "utf8")) as T;
  } catch (err) {
    throw new Error(
      `Data serving tidak ditemukan: ${path}. Jalankan "uv run python -m pihps.serving demo" ` +
        `atau "... download" dulu. (${String(err)})`,
    );
  }
  cache.set(rel, doc);
  return doc;
}

export const getMeta = (): Meta => read<Meta>("meta.json");
export const getWilayah = (kode: string): WilayahDoc => read<WilayahDoc>(`wilayah/${kode}.json`);
export const getPeta = (slug: string): PetaDoc => read<PetaDoc>(`peta/${slug}.json`);
export const getTren = (id: string): TrenDoc => read<TrenDoc>(`tren/${id}.json`);

export function komoditasMap(meta: Meta): Map<string, Komoditas> {
  return new Map(meta.komoditas.map((k) => [k.id, k]));
}
