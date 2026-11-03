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

/**
 * Garis kecil 90 hari. Nilai null memutus garis; titik terakhir ditandai.
 * Koordinat dibulatkan pada resolusi 2x lalu ditulis relatif ("l dx dy") supaya HTML ringkas:
 * satu halaman memuat ±100 sparkline (4 jenis pasar).
 */
export function sparkline(values: (number | null)[], { width = 120, height = 32 } = {}): Raw {
  const pts = values.map((v, i) => [i, v] as const).filter((p): p is readonly [number, number] => p[1] != null);
  if (pts.length < 2) return raw("");
  const ys = pts.map((p) => p[1]);
  const min = Math.min(...ys);
  const max = Math.max(...ys);
  const span = max - min || 1;
  const n = Math.max(values.length - 1, 1);
  const W = width * 2;
  const H = height * 2;
  const pad = 6;
  const x = (i: number) => Math.round((i / n) * (W - 2 * pad) + pad);
  const y = (v: number) => Math.round(H - pad - ((v - min) / span) * (H - 2 * pad));
  let d = "";
  let prev = -2;
  let px = 0;
  let py = 0;
  for (const [i, v] of pts) {
    const cx = x(i);
    const cy = y(v);
    if (i === prev + 1) {
      const dx = cx - px;
      const dy = cy - py;
      d += `l${dx}${dy < 0 ? "" : " "}${dy}`;
    } else d += `M${cx} ${cy}`;
    prev = i;
    px = cx;
    py = cy;
  }
  const last = pts[pts.length - 1]!;
  return html`<svg class="spark" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" aria-hidden="true" focusable="false"><path d="${d}" /><path class="spark__titik" d="M${x(last[0])} ${y(last[1])}h0" /></svg>`;
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

/** Semua baris komoditas (level 2) dikelompokkan per kategori, urut sesuai PIHPS. */
export function gridKomoditas(pasar: PasarWilayah, ctx: RenderCtx): Raw {
  const byId = new Map(pasar.terkini.map((t) => [t.komoditas_id, t]));
  const sections = ctx.kategori
    .map((kat) => {
      const items = kat.komoditas.map((id) => byId.get(id)).filter((t): t is Terkini => t != null);
      if (items.length === 0) return "";
      const rows = items.map((t) => kartu(t, pasar.harian.harga[t.komoditas_id] ?? [], ctx));
      // id unik per jenis pasar: keempat panel pasar ada bersamaan di satu halaman
      const id = `kat-p${pasar.jenis_pasar_id}-${kat.id}`;
      return html`<section class="kategori" aria-labelledby="${id}">
  <h3 class="kategori__judul" id="${id}">${kat.nama}</h3>
  <ul class="papan">${rows}</ul>
</section>`;
    })
    .filter(Boolean);
  if (sections.length === 0) {
    return html`<p class="kosong">Belum ada data harga untuk jenis pasar ini.</p>`;
  }
  return html`<div class="papan-kolom">${sections}</div>`;
}

// ------------------------------------------------------------- beranda: sorotan
// Hierarki beranda: (1) judul = satu insight terkuat, (2) kartu sorotan, (3) papan lengkap.

/** Judul insight: perubahan mingguan terbesar (mutlak) di antara komoditas aktif. */
export function judulInsight(pasar: PasarWilayah, ctx: RenderCtx): string {
  const { naik, turun } = penggerak(pasar, ctx);
  const kandidat = [naik, turun].filter((t): t is Terkini => t != null);
  const t = kandidat.sort((a, b) => Math.abs(b.perubahan_pct_7h!) - Math.abs(a.perubahan_pct_7h!))[0];
  if (!t) return "Harga pangan stabil dibanding minggu lalu";
  const nama = ctx.komoditas.get(t.komoditas_id)?.nama ?? t.komoditas_id;
  return `${nama} ${t.arah_7h === "naik" ? "naik" : "turun"} ${persen(Math.abs(t.perubahan_pct_7h!), { tanda: false })} dalam seminggu`;
}

/** "4 naik · 5 turun · 12 stabil" — kalimat pendamping judul. */
export function hitungHtml(r: Ringkasan): Raw {
  if (r.total === 0) return html`<p class="hitung">Belum ada pembanding minggu lalu.</p>`;
  return html`<p class="hitung" aria-label="Dibanding minggu lalu: ${String(r.naik)} naik, ${String(r.turun)} turun, ${String(r.tetap)} stabil">
  <span class="hitung__n ubah--naik"><strong>${String(r.naik)}</strong> naik</span>
  <span class="hitung__n ubah--turun"><strong>${String(r.turun)}</strong> turun</span>
  <span class="hitung__n ubah--tetap"><strong>${String(r.tetap)}</strong> stabil</span>
  <span class="hitung__ket">dari ${String(r.total)} komoditas, dibanding minggu lalu</span>
</p>`;
}

export interface Timpang {
  komoditas_id: string;
  murah: { nama: string; harga: number };
  mahal: { nama: string; harga: number };
  selisih: number; // % termahal di atas termurah
  href: string;
}

interface KartuSorot {
  label: string;
  t: Terkini;
}

function kartuSorot({ label, t }: KartuSorot, seri: (number | null)[], ctx: RenderCtx): Raw {
  const k = ctx.komoditas.get(t.komoditas_id);
  const arah = t.arah_7h ?? "na";
  const ubah =
    !t.arah_7h || t.perubahan_pct_7h == null
      ? html`<span class="ubah ubah--na">Belum ada pembanding</span>`
      : t.arah_7h === "tetap"
        ? html`<span class="ubah ubah--tetap">Stabil dari minggu lalu</span>`
        : html`<span class="ubah ubah--${t.arah_7h}"><span aria-hidden="true">${ARAH_IKON[t.arah_7h]} </span>${ARAH_LABEL[t.arah_7h]} ${persen(Math.abs(t.perubahan_pct_7h), { tanda: false })} <span class="sorot__ket">dari minggu lalu</span></span>`;
  return html`<li class="sorot" data-arah="${arah}">
  <a class="sorot__tautan" href="${ctx.base}komoditas/${t.komoditas_id}/">
    <span class="sorot__label">${label}</span>
    <span class="sorot__nama">${k?.nama ?? t.komoditas_id}</span>
    <span class="sorot__harga"><data value="${t.harga}">${rupiah(t.harga)}</data><span class="kartu__satuan">${satuan(k?.satuan)}</span></span>
    ${ubah}
    ${sparkline(seri, { width: 200, height: 40 })}
  </a>
</li>`;
}

function kartuTimpang(t: Timpang, ctx: RenderCtx): Raw {
  const k = ctx.komoditas.get(t.komoditas_id);
  return html`<li class="sorot sorot--timpang">
  <a class="sorot__tautan" href="${t.href}">
    <span class="sorot__label">Paling timpang antarprovinsi</span>
    <span class="sorot__nama">${k?.nama ?? t.komoditas_id}</span>
    <span class="sorot__harga sorot__harga--rentang">${rupiah(t.murah.harga)}<span class="sorot__sd">–</span>${rupiah(t.mahal.harga)}</span>
    <span class="ubah">Termahal ${persen(t.selisih, { tanda: false })} di atas termurah</span>
    <span class="sorot__provinsi">${t.murah.nama} → ${t.mahal.nama} · lihat peta</span>
  </a>
</li>`;
}

/**
 * Kartu sorotan: kenaikan & penurunan terbesar, harga beras (acuan), dan satu sorotan wilayah
 * (nasional: komoditas paling timpang antarprovinsi; daerah: paling jauh di atas nasional).
 */
export function sorotanHtml(pasar: PasarWilayah, ctx: RenderCtx, timpang: Timpang[] = []): Raw {
  const aktif = aktifLevel2(pasar, ctx);
  const { naik, turun } = penggerak(pasar, ctx);
  const dipakai = new Set<string>();
  const kartuList: KartuSorot[] = [];
  const tambah = (label: string, t: Terkini | undefined) => {
    if (!t || dipakai.has(t.komoditas_id)) return;
    dipakai.add(t.komoditas_id);
    kartuList.push({ label, t });
  };
  tambah("Naik paling tinggi", naik);
  tambah("Turun paling dalam", turun);
  const beras = aktif.find((t) => t.komoditas_id === BERAS_ACUAN) ?? aktif.find((t) => ctx.komoditas.get(t.komoditas_id)?.nama.startsWith("Beras"));
  tambah("Harga beras", beras);
  if (!ctx.isNasional) {
    const atas = aktif
      .filter((t) => t.selisih_pct_nasional != null && t.selisih_pct_nasional >= 1 && !dipakai.has(t.komoditas_id))
      .sort((a, b) => b.selisih_pct_nasional! - a.selisih_pct_nasional!)[0];
    if (atas) {
      dipakai.add(atas.komoditas_id);
      kartuList.push({ label: `${persen(atas.selisih_pct_nasional, { tanda: false })} di atas nasional`, t: atas });
    }
  }
  // isi sampai 3 kartu harga dengan perubahan sebulan terbesar bila sorotan di atas kosong
  const sebulan = aktif
    .filter((t) => t.perubahan_pct_30h != null && !dipakai.has(t.komoditas_id))
    .sort((a, b) => Math.abs(b.perubahan_pct_30h!) - Math.abs(a.perubahan_pct_30h!));
  while (kartuList.length < 3 && sebulan.length) tambah("Paling bergerak sebulan", sebulan.shift());
  const items = kartuList.map((k) => kartuSorot(k, pasar.harian.harga[k.t.komoditas_id] ?? [], ctx));
  // kandidat timpang terbesar yang belum tampil di kartu lain (hindari komoditas berulang)
  const tp = timpang.find((t) => !dipakai.has(t.komoditas_id)) ?? timpang[0];
  if (ctx.isNasional && tp) items.push(kartuTimpang(tp, ctx));
  if (items.length === 0) return raw("");
  return html`<ul class="sorotan" aria-label="Sorotan">${items}</ul>`;
}

/** Komoditas acuan untuk kartu "Harga beras" (Beras Kualitas Medium I). */
export const BERAS_ACUAN = "com_3";

/** Satu panel jenis pasar di beranda/wilayah: hitungan, sorotan, papan lengkap. */
export function panelBeranda(pasar: PasarWilayah, ctx: RenderCtx, timpang: Timpang[] = []): Raw {
  return html`${hitungHtml(ringkasan(pasar, ctx))}${sorotanHtml(pasar, ctx, timpang)}
<section class="papan-bagian" aria-label="Semua komoditas">
  <div class="papan-bagian__kepala">
    <h2 class="label">Semua komoditas</h2>
    <p class="papan__legenda">Garis: 90 hari terakhir · %: dari minggu lalu</p>
  </div>
  ${gridKomoditas(pasar, ctx)}
</section>`;
}
