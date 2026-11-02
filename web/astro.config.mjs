// Situs statis. Di GitHub Pages situs berada di /<repo>/, jadi `base` diatur lewat env
// (SITE_BASE=/PIHPS saat build CI; kosong untuk pengembangan lokal).
import { defineConfig } from "astro/config";

const base = process.env.SITE_BASE ?? "/";
const site = process.env.SITE_URL ?? "https://hafidznrg.github.io";

export default defineConfig({
  site,
  base,
  trailingSlash: "always",
  build: { format: "directory" },
  // Data serving & Parquet disalin ke public/data saat build; jangan dipantau watcher dev.
  vite: {
    server: { watch: { ignored: ["**/public/data/**"] } },
    build: { chunkSizeWarningLimit: 900 },
  },
});
