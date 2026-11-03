// Logika peta provinsi (dipakai di build & peramban): kelas warna terhadap rata-rata nasional,
// sorotan termahal/termurah, legenda, dan tabel.
import { html, type Raw } from "./html";
import { persen, rupiah } from "./format";
import type { PetaBaris } from "./types";

/** Kelas warna: jauh lebih murah, lebih murah, setara, lebih mahal, jauh lebih mahal, tanpa data. */
export type Kelas = "jm" | "m" | "s" | "h" | "jh" | "na";

// Ambang tetap (bukan kuantil) supaya arti warna sama untuk semua komoditas: "jauh" berarti
// selisih ≥ 15% dari rata-rata nasional, "setara" berarti kurang dari 5%.
export const AMBANG = { setara: 5, jauh: 15 } as const;

export const KELAS: { id: Exclude<Kelas, "na">; label: string; rentang: string }[] = [
  { id: "jm", label: "Jauh lebih murah", rentang: "≥15% di bawah" },
  { id: "m", label: "Lebih murah", rentang: "5–15% di bawah" },
  { id: "s", label: "Setara", rentang: "selisih <5%" },
  { id: "h", label: "Lebih mahal", rentang: "5–15% di atas" },
  { id: "jh", label: "Jauh lebih mahal", rentang: "≥15% di atas" },
];

export function kelasOf(selisih: number | null | undefined): Kelas {
  if (selisih == null) return "na";
  if (selisih <= -AMBANG.jauh) return "jm";
  if (selisih <= -AMBANG.setara) return "m";
  if (selisih < AMBANG.setara) return "s";
  if (selisih < AMBANG.jauh) return "h";
  return "jh";
}

/** Baris aktif, dari termahal ke termurah. */
export function urutkan(rows: PetaBaris[]): PetaBaris[] {
  return rows.filter((r) => r.is_aktif).sort((a, b) => b.harga - a.harga || a.nama.localeCompare(b.nama, "id"));
}

/** Rata-rata nasional diturunkan dari harga & selisih tiap provinsi (median, tahan pembulatan). */
export function nasionalDari(rows: PetaBaris[]): number | null {
  const v = rows
    .filter((r) => r.is_aktif && r.selisih_pct_nasional != null && r.selisih_pct_nasional > -100)
    .map((r) => r.harga / (1 + r.selisih_pct_nasional! / 100))
    .sort((a, b) => a - b);
  if (v.length === 0) return null;
  const m = v.length % 2 ? v[(v.length - 1) / 2]! : (v[v.length / 2 - 1]! + v[v.length / 2]!) / 2;
  return Math.round(m);
}

export interface RingkasPeta {
  termahal: PetaBaris;
  termurah: PetaBaris;
  selisih: number; // % termahal di atas termurah
  nasional: number | null;
  jumlah: Record<Exclude<Kelas, "na">, number>;
  n: number;
}

export function ringkas(rows: PetaBaris[]): RingkasPeta | null {
  const aktif = urutkan(rows);
  const termahal = aktif[0];
  const termurah = aktif[aktif.length - 1];
  if (!termahal || !termurah) return null;
  const jumlah = { jm: 0, m: 0, s: 0, h: 0, jh: 0 };
  for (const r of aktif) {
    const k = kelasOf(r.selisih_pct_nasional);
    if (k !== "na") jumlah[k] += 1;
  }
  return {
    termahal,
    termurah,
    selisih: ((termahal.harga - termurah.harga) / termurah.harga) * 100,
    nasional: nasionalDari(rows),
    jumlah,
    n: aktif.length,
  };
}

/** Kalimat ringkas (teks biasa) untuk pembaca layar & deskripsi. */
export function ringkasPeta(rows: PetaBaris[]): string {
  const r = ringkas(rows);
  if (!r) return "";
  return `Termahal ${r.termahal.nama} (${rupiah(r.termahal.harga)}), termurah ${r.termurah.nama} (${rupiah(r.termurah.harga)}), selisih ${persen(r.selisih, { tanda: false })}.`;
}

const selisihKata = (s: number | null) =>
  s == null ? "" : Math.abs(s) < 0.05 ? "sama dengan nasional" : `${persen(Math.abs(s), { tanda: false })} ${s > 0 ? "di atas" : "di bawah"} nasional`;

/** Tiga angka utama di atas peta: termahal, termurah, rata-rata nasional. */
export function sorotanPeta(rows: PetaBaris[], satuan: string): Raw {
  const r = ringkas(rows);
  if (!r) return html`<p class="kosong">Belum ada data provinsi untuk pilihan ini.</p>`;
  const kartu = (label: string, cls: string, b: PetaBaris) =>
    html`<div class="sorot-peta sorot-peta--${cls}" data-kode="${b.kode_bps ?? ""}">
  <p class="sorot-peta__label"><span class="penanda" aria-hidden="true"></span>${label}</p>
  <p class="sorot-peta__nama">${b.nama}</p>
  <p class="sorot-peta__angka">${rupiah(b.harga)}<span class="kartu__satuan">${satuan}</span></p>
  <p class="sorot-peta__ket">${selisihKata(b.selisih_pct_nasional)}</p>
</div>`;
  return html`${kartu("Termahal", "mahal", r.termahal)}${kartu("Termurah", "murah", r.termurah)}
<div class="sorot-peta sorot-peta--nas">
  <p class="sorot-peta__label">Rata-rata nasional</p>
  <p class="sorot-peta__angka">${rupiah(r.nasional)}<span class="kartu__satuan">${satuan}</span></p>
  <p class="sorot-peta__ket">Termahal ${persen(r.selisih, { tanda: false })} di atas termurah · ${r.n} provinsi</p>
</div>`;
}

/** Legenda berjenjang + jumlah provinsi per kelas. */
export function legendaPeta(rows: PetaBaris[]): Raw {
  const r = ringkas(rows);
  const items = KELAS.map(
    (k) => html`<li class="legenda__item" data-kelas="${k.id}">
  <span class="legenda__warna k-${k.id}" aria-hidden="true"></span>
  <span class="legenda__label">${k.label}</span>
  <span class="legenda__rentang">${k.rentang}</span>
  <span class="legenda__n">${r ? String(r.jumlah[k.id]) : "0"} prov</span>
</li>`,
  );
  return html`<ul class="legenda" aria-label="Arti warna: dibanding rata-rata nasional">${items}</ul>`;
}

export function tabelPeta(rows: PetaBaris[], base: string): Raw {
  const aktif = urutkan(rows);
  if (aktif.length === 0) return html`<p class="kosong">Belum ada data provinsi untuk pilihan ini.</p>`;
  const body = aktif.map(
    (r, i) => html`<tr data-kode="${r.kode_bps ?? ""}">
  <td class="angka tabel-peta__no">${i + 1}</td>
  <td><a href="${base}wilayah/${r.kode_wilayah}/">${r.nama}</a></td>
  <td class="angka">${rupiah(r.harga)}</td>
  <td class="angka"><span class="swatch k-${kelasOf(r.selisih_pct_nasional)}" aria-hidden="true"></span>${persen(r.selisih_pct_nasional)}</td>
  <td class="angka tabel-peta__mgg">${persen(r.perubahan_pct_7h)}</td>
</tr>`,
  );
  return html`<table class="tabel-peta">
  <caption class="sr-only">Harga per provinsi, dari termahal</caption>
  <thead><tr><th class="angka">#</th><th>Provinsi</th><th class="angka">Harga</th><th class="angka">vs nasional</th><th class="angka tabel-peta__mgg">1 mgg</th></tr></thead>
  <tbody>${body}</tbody>
</table>`;
}

/** Data warna per provinsi (kode BPS -> kelas) untuk mewarnai SVG. */
export function kelasPerProvinsi(rows: PetaBaris[]): Map<string, Kelas> {
  const m = new Map<string, Kelas>();
  for (const r of rows) if (r.is_aktif && r.kode_bps) m.set(r.kode_bps, kelasOf(r.selisih_pct_nasional));
  return m;
}


export interface TimpangPeta {
  komoditas_id: string;
  murah: PetaBaris;
  mahal: PetaBaris;
  selisih: number;
}

/** Komoditas diurutkan dari selisih termahal–termurah antarprovinsi terbesar (sorotan beranda). */
export function urutTimpang(doc: { komoditas: Record<string, PetaBaris[]> }, ids: string[], minProvinsi = 5): TimpangPeta[] {
  const out: TimpangPeta[] = [];
  for (const id of ids) {
    const r = ringkas(doc.komoditas[id] ?? []);
    if (r && r.n >= minProvinsi) out.push({ komoditas_id: id, murah: r.termurah, mahal: r.termahal, selisih: r.selisih });
  }
  return out.sort((a, b) => b.selisih - a.selisih);
}

export function palingTimpang(doc: { komoditas: Record<string, PetaBaris[]> }, ids: string[], minProvinsi = 5): TimpangPeta | null {
  return urutTimpang(doc, ids, minProvinsi)[0] ?? null;
}
