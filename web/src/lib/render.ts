// Render papan harga per wilayah & jenis pasar. Fungsi murni -> HTML string, dipakai di
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
const ARAH_IKON: Record<Arah, string> = { naik: "▲", turun: "▼", tetap: "–" };

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

/** Perubahan seminggu dengan kata lengkap (halaman komoditas). */
export function badgeArah(t: Terkini): Raw {
  if (!t.arah_7h || t.perubahan_pct_7h == null) {
    return html`<p class="ubah ubah--na">Belum ada pembanding minggu lalu</p>`;
  }
  const label = t.arah_7h === "tetap" ? "Stabil" : `${ARAH_LABEL[t.arah_7h]} ${persen(t.perubahan_pct_7h, { tanda: false })}`;
  return html`<p class="ubah ubah--${t.arah_7h}"><span aria-hidden="true">${ARAH_IKON[t.arah_7h]}</span> ${label} <span class="ubah__ket">dari minggu lalu</span></p>`;
}

/** Perubahan seminggu ringkas untuk baris papan: "▲ 2,8%"; kata lengkap untuk pembaca layar. */
export function ubahRingkas(t: Terkini): Raw {
  if (!t.arah_7h || t.perubahan_pct_7h == null) {
    return html`<span class="ubah ubah--na" title="Belum ada pembanding minggu lalu">–<span class="sr-only"> belum ada pembanding minggu lalu</span></span>`;
  }
  const angka = t.arah_7h === "tetap" ? "0%" : persen(t.perubahan_pct_7h, { tanda: false });
  const kata = t.arah_7h === "tetap" ? "Stabil" : `${ARAH_LABEL[t.arah_7h]} ${angka}`;
  return html`<span class="ubah ubah--${t.arah_7h}" title="${kata} dari minggu lalu"><span aria-hidden="true">${ARAH_IKON[t.arah_7h]} ${angka}</span><span class="sr-only">${kata} dari minggu lalu</span></span>`;
}

function bandingNasional(t: Terkini, ctx: RenderCtx): Raw {
  const s = t.selisih_pct_nasional;
  if (ctx.isNasional || s == null) return raw("");
  if (Math.abs(s) < 1) return html`<span class="banding">Setara rata-rata nasional</span>`;
  const arah = s > 0 ? "di atas" : "di bawah";
  return html`<span class="banding banding--${s > 0 ? "atas" : "bawah"}">${persen(Math.abs(s), { tanda: false })} ${arah} rata-rata nasional</span>`;
}

/** Satu baris papan harga. */
export function kartu(t: Terkini, seri: (number | null)[], ctx: RenderCtx): Raw {
  const k = ctx.komoditas.get(t.komoditas_id);
  const nama = k?.nama ?? t.komoditas_id;
  const href = `${ctx.base}komoditas/${t.komoditas_id}/`;
  const lama = !t.is_aktif ? html`<span class="lama">Data terakhir ${tanggalPendek(t.tanggal)}</span>` : raw("");
  const sub = bandingNasional(t, ctx).value || lama.value ? html`<span class="kartu__sub">${bandingNasional(t, ctx)}${lama}</span>` : raw("");
  return html`<li class="kartu${t.is_aktif ? "" : " kartu--lama"}" data-arah="${t.arah_7h ?? "na"}">
  <a class="kartu__tautan" href="${href}">
    <span class="kartu__nama">${nama}${sub}</span>
    ${sparkline(seri)}
    <span class="kartu__harga"><data value="${t.harga}">${rupiah(t.harga)}</data><span class="kartu__satuan">${satuan(k?.satuan)}</span></span>
    ${ubahRingkas(t)}
  </a>
</li>`;
}

export interface Ringkasan {
  naik: number;
  turun: number;
  tetap: number;
  total: number;
}

function aktifLevel2(pasar: PasarWilayah, ctx: RenderCtx): Terkini[] {
  return pasar.terkini.filter((t) => t.is_aktif && ctx.komoditas.get(t.komoditas_id)?.level === 2);
}

export function ringkasan(pasar: PasarWilayah, ctx: RenderCtx): Ringkasan {
  const r: Ringkasan = { naik: 0, turun: 0, tetap: 0, total: 0 };
  for (const t of aktifLevel2(pasar, ctx)) {
    if (!t.arah_7h) continue;
    r[t.arah_7h] += 1;
    r.total += 1;
  }
  return r;
}

/** Komoditas dengan kenaikan & penurunan seminggu terbesar (abaikan yang "tetap"). */
export function penggerak(pasar: PasarWilayah, ctx: RenderCtx): { naik: Terkini | undefined; turun: Terkini | undefined } {
  const ada = aktifLevel2(pasar, ctx).filter((t) => t.perubahan_pct_7h != null && t.arah_7h && t.arah_7h !== "tetap");
  const naik = ada.filter((t) => t.arah_7h === "naik").sort((a, b) => b.perubahan_pct_7h! - a.perubahan_pct_7h!)[0];
  const turun = ada.filter((t) => t.arah_7h === "turun").sort((a, b) => a.perubahan_pct_7h! - b.perubahan_pct_7h!)[0];
  return { naik, turun };
}

/** Ringkasan sebagai kalimat pembuka: hitungan naik/turun + penggerak terbesar. */
export function ringkasanHtml(r: Ringkasan, pasar?: PasarWilayah, ctx?: RenderCtx): Raw {
  if (r.total === 0) return html`<div class="ringkasan"><p class="ringkasan__teks">Belum ada pembanding minggu lalu.</p></div>`;
  const p = pasar && ctx ? penggerak(pasar, ctx) : { naik: undefined, turun: undefined };
  const nama = (t: Terkini) => ctx?.komoditas.get(t.komoditas_id)?.nama ?? t.komoditas_id;
  const tautan = (t: Terkini) => html`<a href="${ctx?.base ?? "/"}komoditas/${t.komoditas_id}/">${nama(t)}</a>`;
  const kalimat: Raw[] = [];
  if (p.naik) kalimat.push(html`Kenaikan terbesar ${tautan(p.naik)} <span class="ubah--naik">+${persen(p.naik.perubahan_pct_7h, { tanda: false })}</span>`);
  if (p.turun) kalimat.push(html`penurunan terbesar ${tautan(p.turun)} <span class="ubah--turun">−${persen(p.turun.perubahan_pct_7h, { tanda: false })}</span>`);
  const kedua = kalimat.length ? html` ${kalimat[0]}${kalimat[1] ? html`; ${kalimat[1]}` : ""}.` : raw("");
  return html`<div class="ringkasan" aria-label="Ringkasan perubahan dari minggu lalu">
  <p class="ringkasan__angka"><span class="ubah--naik"><strong>${r.naik}</strong> naik</span><span class="ubah--turun"><strong>${r.turun}</strong> turun</span><span class="ubah--tetap"><strong>${r.tetap}</strong> stabil</span></p>
  <p class="ringkasan__teks">Dibanding seminggu lalu, dari ${r.total} komoditas.${kedua}</p>
</div>`;
}

/** Semua baris komoditas (level 2) dikelompokkan per kategori, urut sesuai PIHPS. */
export function gridKomoditas(pasar: PasarWilayah, ctx: RenderCtx): Raw {
  const byId = new Map(pasar.terkini.map((t) => [t.komoditas_id, t]));
  const sections = ctx.kategori
    .map((kat) => {
      const items = kat.komoditas.map((id) => byId.get(id)).filter((t): t is Terkini => t != null);
      if (items.length === 0) return "";
      const rows = items.map((t) => kartu(t, pasar.harian.harga[t.komoditas_id] ?? [], ctx));
      return html`<section class="kategori" aria-labelledby="kat-${kat.id}">
  <h2 class="kategori__judul" id="kat-${kat.id}">${kat.nama}</h2>
  <ul class="papan">${rows}</ul>
</section>`;
    })
    .filter(Boolean);
  if (sections.length === 0) {
    return html`<p class="kosong">Belum ada data harga untuk jenis pasar ini.</p>`;
  }
  return html`<div class="papan-kolom">${sections}</div>`;
}

export function panelPasar(pasar: PasarWilayah, ctx: RenderCtx): Raw {
  return html`${ringkasanHtml(ringkasan(pasar, ctx), pasar, ctx)}<p class="papan__legenda">Harga per kilogram. Garis kecil: 90 hari terakhir. Persen: perubahan dari minggu lalu.</p>${gridKomoditas(pasar, ctx)}`;
}
