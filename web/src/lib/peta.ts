// Tabel harga provinsi untuk halaman peta (dipakai di build & peramban).
import { html, type Raw } from "./html";
import { persen, rupiah } from "./format";
import type { PetaBaris } from "./types";

export function urutkan(rows: PetaBaris[]): PetaBaris[] {
  return rows.filter((r) => r.is_aktif).sort((a, b) => a.harga - b.harga);
}

export function tabelPeta(rows: PetaBaris[], base: string): Raw {
  const aktif = urutkan(rows);
  if (aktif.length === 0) return html`<p class="kosong">Belum ada data provinsi untuk pilihan ini.</p>`;
  const body = aktif.map(
    (r, i) => html`<tr>
  <td class="angka">${i + 1}</td>
  <td><a href="${base}wilayah/${r.kode_wilayah}/">${r.nama}</a></td>
  <td class="angka">${rupiah(r.harga)}</td>
  <td class="angka">${persen(r.selisih_pct_nasional)}</td>
  <td class="angka">${persen(r.perubahan_pct_7h)}</td>
</tr>`,
  );
  return html`<table>
  <caption class="sr-only">Harga per provinsi, dari termurah</caption>
  <thead><tr><th class="angka">#</th><th>Provinsi</th><th class="angka">Harga</th><th class="angka">vs nasional</th><th class="angka">vs minggu lalu</th></tr></thead>
  <tbody>${body}</tbody>
</table>`;
}

export function ringkasPeta(rows: PetaBaris[]): string {
  const aktif = urutkan(rows);
  const a = aktif[0];
  const z = aktif[aktif.length - 1];
  if (!a || !z) return "";
  const beda = ((z.harga - a.harga) / a.harga) * 100;
  return `Termurah ${a.nama} (${rupiah(a.harga)}), termahal ${z.nama} (${rupiah(z.harga)}), selisih ${persen(beda, { tanda: false })}.`;
}
