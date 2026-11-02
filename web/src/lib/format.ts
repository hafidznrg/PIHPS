// Format angka & tanggal gaya Indonesia. Tanggal ISO diperlakukan sebagai tanggal kalender
// (UTC) supaya tidak bergeser oleh zona waktu peramban.

const rupiahFmt = new Intl.NumberFormat("id-ID", { maximumFractionDigits: 0 });
const pctFmt = new Intl.NumberFormat("id-ID", { minimumFractionDigits: 1, maximumFractionDigits: 1 });

export function rupiah(n: number | null | undefined): string {
  return n == null ? "–" : `Rp${rupiahFmt.format(n)}`;
}

export function angka(n: number | null | undefined): string {
  return n == null ? "–" : rupiahFmt.format(n);
}

/** 3.14 -> "+3,1%", -0.4 -> "−0,4%" (tanda minus tipografis), 0 -> "0,0%". */
export function persen(p: number | null | undefined, { tanda = true } = {}): string {
  if (p == null) return "–";
  const abs = pctFmt.format(Math.abs(p));
  if (!tanda || abs === pctFmt.format(0)) return `${abs}%`;
  return `${p > 0 ? "+" : "−"}${abs}%`;
}

function utc(iso: string): Date {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(Date.UTC(y ?? 1970, (m ?? 1) - 1, d ?? 1));
}

const panjangFmt = new Intl.DateTimeFormat("id-ID", {
  weekday: "long",
  day: "numeric",
  month: "long",
  year: "numeric",
  timeZone: "UTC",
});
const pendekFmt = new Intl.DateTimeFormat("id-ID", {
  day: "numeric",
  month: "short",
  year: "numeric",
  timeZone: "UTC",
});
const bulanFmt = new Intl.DateTimeFormat("id-ID", { month: "short", year: "numeric", timeZone: "UTC" });

/** "2026-10-30" -> "Jumat, 30 Oktober 2026" */
export const tanggalPanjang = (iso: string): string => panjangFmt.format(utc(iso));
/** "2026-10-30" -> "30 Okt 2026" */
export const tanggalPendek = (iso: string): string => pendekFmt.format(utc(iso));
/** "2026-10" -> "Okt 2026" */
export const bulanPendek = (ym: string): string => bulanFmt.format(utc(`${ym}-01`));

/** Selisih hari kalender antara dua tanggal ISO (b - a). */
export function selisihHari(a: string, b: string): number {
  return Math.round((utc(b).getTime() - utc(a).getTime()) / 86_400_000);
}

export function satuan(s: string | null | undefined): string {
  return s ? `/${s}` : "";
}
