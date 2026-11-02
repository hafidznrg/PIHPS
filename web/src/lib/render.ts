// Render kartu harga per wilayah & jenis pasar. Fungsi murni -> HTML string, dipakai di
// build (halaman statis) dan di peramban (saat pengguna mengganti jenis pasar).

import { html, raw, type Raw } from "./html";
import { persen, rupiah, satuan, tanggalPendek } from "./format";
import type { Arah, Kategori, Komoditas, PasarWilayah, Terkini } from "./types";

export interface RenderCtx {
  base: string; // import.meta.env.BASE_URL, diakhiri "/"
  komoditas: Map<string, Komoditas>;
  kategori: Kategori[];
  isNasional: boolean;
}

const ARAH_LABEL: Record<Arah, string> = { naik: "Naik", turun: "Turun", tetap: "Stabil" };
const ARAH_IKON: Record<Arah, string> = { naik: "▲", turun: "▼", tetap: "●" };

/** Garis kecil 90 hari. Nilai null memutus garis; titik terakhir ditandai. */
export function sparkline(values: (number | null)[], { width = 120, height = 32 } = {}): Raw {
  const pts = values.map((v, i) => [i, v] as const).filter((p): p is readonly [number, number] => p[1] != null);
  if (pts.length < 2) return raw("");
  const ys = pts.map((p) => p[1]);
  const min = Math.min(...ys);
  const max = Math.max(...ys);
  const span = max - min || 1;
  const n = Math.max(values.length - 1, 1);
  const pad = 3;
  const x = (i: number) => ((i / n) * (width - 2 * pad) + pad).toFixed(1);
  const y = (v: number) => (height - pad - ((v - min) / span) * (height - 2 * pad)).toFixed(1);
  let d = "";
  let prev = -2;
  for (const [i, v] of pts) {
    d += `${i === prev + 1 ? "L" : "M"}${x(i)} ${y(v)}`;
    prev = i;
  }
  const last = pts[pts.length - 1]!;
  return html`<svg class="spark" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" aria-hidden="true" focusable="false"><path d="${d}" /><path class="spark__titik" d="M${x(last[0])} ${y(last[1])}h0" /></svg>`;
}

export function badgeArah(t: Terkini): Raw {
  if (!t.arah_7h || t.perubahan_pct_7h == null) {
    return html`<p class="ubah ubah--na">Belum ada pembanding minggu lalu</p>`;
  }
  const label = t.arah_7h === "tetap" ? "Stabil" : `${ARAH_LABEL[t.arah_7h]} ${persen(t.perubahan_pct_7h, { tanda: false })}`;
  return html`<p class="ubah ubah--${t.arah_7h}"><span aria-hidden="true">${ARAH_IKON[t.arah_7h]}</span> ${label} <span class="ubah__ket">dari minggu lalu</span></p>`;
}

function bandingNasional(t: Terkini, ctx: RenderCtx): Raw {
  const s = t.selisih_pct_nasional;
  if (ctx.isNasional || s == null) return raw("");
  if (Math.abs(s) < 1) return html`<p class="banding">Setara rata-rata nasional</p>`;
  const arah = s > 0 ? "di atas" : "di bawah";
  return html`<p class="banding">${persen(Math.abs(s), { tanda: false })} ${arah} rata-rata nasional</p>`;
}

export function kartu(t: Terkini, seri: (number | null)[], ctx: RenderCtx): Raw {
  const k = ctx.komoditas.get(t.komoditas_id);
  const nama = k?.nama ?? t.komoditas_id;
  const href = `${ctx.base}komoditas/${t.komoditas_id}/`;
  const lama = !t.is_aktif
    ? html`<p class="lama">Data terakhir ${tanggalPendek(t.tanggal)}</p>`
    : raw("");
  return html`<li class="kartu${t.is_aktif ? "" : " kartu--lama"}" data-arah="${t.arah_7h ?? "na"}">
  <a class="kartu__tautan" href="${href}">
    <h3 class="kartu__nama">${nama}</h3>
    <p class="kartu__harga"><data value="${t.harga}">${rupiah(t.harga)}</data><span class="kartu__satuan">${satuan(k?.satuan)}</span></p>
    ${badgeArah(t)}
    ${sparkline(seri)}
    ${bandingNasional(t, ctx)}
    ${lama}
  </a>
</li>`;
}

export interface Ringkasan {
  naik: number;
  turun: number;
  tetap: number;
  total: number;
}

export function ringkasan(pasar: PasarWilayah, ctx: RenderCtx): Ringkasan {
  const r: Ringkasan = { naik: 0, turun: 0, tetap: 0, total: 0 };
  for (const t of pasar.terkini) {
    if (!t.is_aktif || ctx.komoditas.get(t.komoditas_id)?.level !== 2 || !t.arah_7h) continue;
    r[t.arah_7h] += 1;
    r.total += 1;
  }
  return r;
}

export function ringkasanHtml(r: Ringkasan): Raw {
  if (r.total === 0) return html`<p class="ringkasan">Belum ada pembanding minggu lalu.</p>`;
  return html`<ul class="ringkasan" aria-label="Ringkasan perubahan dari minggu lalu">
  <li class="ringkasan__item ubah--naik"><strong>${r.naik}</strong> naik</li>
  <li class="ringkasan__item ubah--turun"><strong>${r.turun}</strong> turun</li>
  <li class="ringkasan__item ubah--tetap"><strong>${r.tetap}</strong> stabil</li>
</ul>`;
}

/** Semua kartu komoditas (level 2) dikelompokkan per kategori, urut sesuai PIHPS. */
export function gridKomoditas(pasar: PasarWilayah, ctx: RenderCtx): Raw {
  const byId = new Map(pasar.terkini.map((t) => [t.komoditas_id, t]));
  const sections = ctx.kategori
    .map((kat) => {
      const items = kat.komoditas.map((id) => byId.get(id)).filter((t): t is Terkini => t != null);
      if (items.length === 0) return "";
      const cards = items.map((t) => kartu(t, pasar.harian.harga[t.komoditas_id] ?? [], ctx));
      return html`<section class="kategori" aria-labelledby="kat-${kat.id}">
  <h2 class="kategori__judul" id="kat-${kat.id}">${kat.nama}</h2>
  <ul class="kartu-grid">${cards}</ul>
</section>`;
    })
    .filter(Boolean);
  if (sections.length === 0) {
    return html`<p class="kosong">Belum ada data harga untuk jenis pasar ini.</p>`;
  }
  return html`${sections}`;
}

export function panelPasar(pasar: PasarWilayah, ctx: RenderCtx): Raw {
  return html`${ringkasanHtml(ringkasan(pasar, ctx))}${gridKomoditas(pasar, ctx)}`;
}
