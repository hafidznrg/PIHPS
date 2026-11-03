// SEMENTARA (dihapus sebelum PR siap): screenshot situs hasil build data nyata untuk PR.
const { chromium, devices } = require("@playwright/test");
const base = process.env.BASE_URL;
(async () => {
  const b = await chromium.launch();
  for (const [nama, url] of [["beranda", ""], ["peta", "peta/"], ["peta-cabai", "peta/?k=com_13&p=pasar_tradisional"]]) {
    for (const [mode, opt] of [
      ["hp", { ...devices["Pixel 7"] }],
      ["desktop", { viewport: { width: 1440, height: 900 }, deviceScaleFactor: 2 }],
    ]) {
      for (const scheme of ["light", "dark"]) {
        const ctx = await b.newContext({ ...opt, colorScheme: scheme });
        const p = await ctx.newPage();
        await p.goto(base + url, { waitUntil: "networkidle" });
        await p.waitForTimeout(500);
        await p.screenshot({ path: `layar/${nama}-${mode}-${scheme}.png`, fullPage: mode === "hp" && nama === "beranda" ? false : true });
        await ctx.close();
      }
    }
  }
  await b.close();
})();
