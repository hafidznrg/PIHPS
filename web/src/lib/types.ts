// Tipe kontrak serving layer (versi skema 1). Sumber kebenaran: JSON Schema di
// src/pihps/serving_schemas/*.schema.json; tes `contract.test.ts` memvalidasi bahwa data
// yang dipakai situs cocok dengan tipe ini lewat skema yang sama.

export type IsoDate = string; // YYYY-MM-DD
export type KomoditasId = `cat_${number}` | `com_${number}`;
export type KodeWilayah = string; // nasional | prov-<id> | kab-<id>
export type JenisPasarId = 1 | 2 | 3 | 4;
export type Arah = "naik" | "turun" | "tetap";
export type LevelWilayah = "nasional" | "provinsi" | "kabkota";

export interface JenisPasar {
  id: JenisPasarId;
  slug: "pasar_tradisional" | "pasar_modern" | "pedagang_besar" | "produsen";
  nama: string;
  rantai_pasok: "eceran" | "grosir" | "produsen";
}

export interface Het {
  harga: number;
  satuan: string | null;
  berlaku_mulai: IsoDate | null;
  sumber: string | null;
}

export interface Komoditas {
  id: KomoditasId;
  nama: string;
  tipe: "kategori" | "komoditas";
  level: 1 | 2;
  kategori_id: KomoditasId;
  satuan: string | null;
  urutan: number | null;
  het: Het | null;
}

export interface Kategori {
  id: KomoditasId;
  nama: string;
  urutan: number | null;
  komoditas: KomoditasId[];
}

export interface WilayahRef {
  kode: KodeWilayah;
  nama: string;
  level: LevelWilayah;
  kode_provinsi: KodeWilayah | null;
  nama_provinsi: string | null;
  kode_bps: string | null;
}

export interface WilayahMeta extends WilayahRef {
  jenis_pasar: JenisPasarId[];
  jenis_pasar_aktif: JenisPasarId[];
  tanggal_terakhir: IsoDate;
  is_aktif: boolean;
}

export interface Meta {
  schema_version: 1;
  dibuat_pada: string;
  tanggal_acuan: IsoDate;
  sumber: { nama: string; url: string };
  jenis_pasar: JenisPasar[];
  kategori: Kategori[];
  komoditas: Komoditas[];
  wilayah: WilayahMeta[];
  statistik: {
    sel_harga: number;
    tanggal_awal: IsoDate;
    tanggal_akhir: IsoDate;
    sel_outlier: number;
    wilayah: number;
  };
}

export interface Terkini {
  komoditas_id: KomoditasId;
  tanggal: IsoDate;
  harga: number;
  tanggal_sebelumnya: IsoDate | null;
  harga_sebelumnya: number | null;
  harga_7h: number | null;
  harga_30h: number | null;
  harga_1th: number | null;
  perubahan_pct_sebelumnya: number | null;
  perubahan_pct_7h: number | null;
  perubahan_pct_30h: number | null;
  perubahan_pct_1th: number | null;
  arah_7h: Arah | null;
  selisih_pct_nasional: number | null;
  is_aktif: boolean;
}

// Seri kolumnar: satu sumbu waktu bersama + array harga per seri (null = tidak ada data).
export type Seri = Record<string, (number | null)[]>;
export interface SeriHarian {
  tanggal: IsoDate[];
  harga: Seri; // kunci: komoditas_id
}
export interface SeriBulanan {
  bulan: string[]; // YYYY-MM
  harga: Seri; // kunci: komoditas_id
}
export interface SeriMingguan {
  minggu: IsoDate[]; // Senin awal minggu
  harga: Seri; // kunci: jenis_pasar_id ("1".."4")
}

export interface PasarWilayah {
  jenis_pasar_id: JenisPasarId;
  terkini: Terkini[];
  harian: SeriHarian;
  bulanan: SeriBulanan;
}

export interface WilayahDoc {
  schema_version: 1;
  tanggal_acuan: IsoDate;
  wilayah: WilayahRef;
  pasar: PasarWilayah[];
}

export interface PetaBaris {
  kode_wilayah: KodeWilayah;
  kode_bps: string | null;
  nama: string;
  tanggal: IsoDate;
  harga: number;
  perubahan_pct_7h: number | null;
  selisih_pct_nasional: number | null;
  is_aktif: boolean;
}

export interface PetaDoc {
  schema_version: 1;
  tanggal_acuan: IsoDate;
  jenis_pasar_id: JenisPasarId;
  komoditas: Record<string, PetaBaris[]>;
}

export interface ProvinsiTerkini {
  kode_wilayah: KodeWilayah;
  nama: string;
  kode_bps: string | null;
  tanggal: IsoDate;
  harga: number;
  perubahan_pct_7h: number | null;
  selisih_pct_nasional: number | null;
}

export interface TrenDoc {
  schema_version: 1;
  tanggal_acuan: IsoDate;
  komoditas_id: KomoditasId;
  mingguan: SeriMingguan;
  nasional_terkini: (Terkini & { jenis_pasar_id: JenisPasarId })[];
  provinsi_terkini: ProvinsiTerkini[];
}
