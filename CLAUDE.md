# CLAUDE.md

Panduan kerja untuk Claude Code di repo ini. Baca juga `docs/PLAN.md` (rencana & roadmap) dan
`docs/api-notes.md` (dokumentasi API PIHPS) sebelum mulai bekerja.

## Tentang project

Portofolio data engineering end-to-end: harga pangan harian dari PIHPS Nasional (Bank Indonesia)
→ Cloudflare R2 (raw → staging → marts → serving) → web untuk masyarakat umum. Semua di layanan
gratis. Atribusi data selalu ke "PIHPS Nasional – Bank Indonesia".

## Aturan wajib

- **Author commit**: selalu `hafidznrg <hafidznrg.dev@gmail.com>`. Sebelum commit pertama di
  sesi baru, jalankan:
  `git config user.name "hafidznrg" && git config user.email "hafidznrg.dev@gmail.com"`.
  Akhiri pesan commit dengan trailer `Co-Authored-By: Claude <noreply@anthropic.com>`.
  Commit kecil dan bermakna, pesan dalam Bahasa Indonesia.
- **Alur kerja**: kerjakan di branch fitur → PR ke `main`. Jangan push langsung ke `main` kecuali
  perubahan dokumentasi kecil. CI (`ruff check`, `ruff format --check`, `pytest`) harus hijau.
- **Jaringan**: container sesi Claude Code TIDAK bisa mengakses bi.go.id (diblokir allowlist).
  Jangan coba memutarinya. Uji apa pun yang menyentuh PIHPS atau R2 lewat GitHub Actions:
  - workflow baru belum bisa di-`workflow_dispatch` sebelum ada di `main`, jadi tambahkan trigger
    `push` sementara untuk branch fitur, lalu hapus sebelum PR siap;
  - pantau run & baca log dengan `gh api` (REST). GraphQL tidak tersedia.
- **Secret** (sudah ada di GitHub repo secrets, jangan pernah dicetak atau di-commit):
  `R2_ENDPOINT`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET`,
  `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`.
- **Sopan ke server PIHPS**: selalu lewat `PihpsClient` (jeda ≥ 1,5 detik, retry + backoff,
  User-Agent jujur). Satu request per wilayah; rentang tanggal maksimal ±1 bulan per request.
- **Data mentah tidak pernah diubah**: layer raw menyimpan respons API apa adanya.
- **Definisi selesai** untuk tiap fase: PR terbuka, CI hijau, dibuktikan oleh run nyata di
  GitHub Actions (file ada di R2, pesan Telegram terkirim bila relevan), hasil & temuan data aneh
  dilaporkan di deskripsi PR, dan `docs/PLAN.md` diperbarui (status fase + keputusan baru).

## Stack & perintah

- Python 3.12, `uv`, httpx, boto3; transformasi (Fase 2) dengan dbt-duckdb.
- `uv sync` · `uv run pytest -q` · `uv run ruff check .` · `uv run ruff format .`
- Probe API: workflow `probe` (manual). Extractor: `uv run python -m pihps.extract --help`.

## Struktur penting

- `src/pihps/client.py` — client API PIHPS
- `src/pihps/parse.py` — format lebar → baris panjang
- `src/pihps/storage.py` — akses R2
- `src/pihps/notify.py` — Telegram
- `src/pihps/probe.py`, `src/pihps/extract.py` — entry point
- `docs/PLAN.md` — rencana hidup; perbarui saat status atau keputusan berubah
- `docs/api-notes.md`, `docs/raw-layout.md` — referensi teknis

## Pilihan model (hemat kredit)

Implementasi yang lingkupnya jelas → Sonnet atau `opusplan`. Pemodelan data (dbt, SCD2,
pemetaan wilayah) dan evaluasi rencana → Opus. Hindari Fable untuk project ini.
