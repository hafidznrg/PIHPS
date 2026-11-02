// Mode lokal halaman Jelajahi: salin bundle DuckDB-WASM dari node_modules ke public/duckdb
// (dipakai bila PUBLIC_DUCKDB_BUNDLE=local, mis. tes tanpa akses CDN). Produksi memakai
// jsDelivr dengan versi yang sama persis dengan package-lock.
import { copyFileSync, mkdirSync } from "node:fs";
import { join } from "node:path";

const src = join("node_modules", "@duckdb", "duckdb-wasm", "dist");
const dest = join("public", "duckdb");
mkdirSync(dest, { recursive: true });
for (const f of ["duckdb-mvp.wasm", "duckdb-eh.wasm", "duckdb-browser-mvp.worker.js", "duckdb-browser-eh.worker.js"]) {
  copyFileSync(join(src, f), join(dest, f));
}
console.log(`bundle DuckDB-WASM disalin ke ${dest}`);
