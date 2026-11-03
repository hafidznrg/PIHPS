import { expect, test, type Page } from "@playwright/test";

/** Kumpulkan galat JS & console.error selama tes; harus kosong. */
function pantauGalat(page: Page): string[] {
  const errs: string[] = [];
  page.on("pageerror", (e) => errs.push(String(e)));
  page.on("console", (m) => m.type() === "error" && errs.push(m.text()));
  return errs;
}

async function tanpaLuberHorizontal(page: Page) {
  const { sw, cw } = await page.evaluate(() => ({
    sw: document.documentElement.scrollWidth,
    cw: document.documentElement.clientWidth,
  }));
  expect(sw, "halaman tidak boleh bisa digeser ke samping").toBeLessThanOrEqual(cw);
}

test("beranda: judul insight, sorotan, papan, dan grafik", async ({ page }) => {
  const errs = pantauGalat(page);
  await page.goto("./");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(/dalam seminggu|stabil/);
  await expect(page.locator(".kicker").first()).toContainText("Rata-rata nasional");
  const panel = page.locator(".panel-pasar:not([hidden])");
  await expect(panel).toHaveCount(1);
  await expect(panel.locator(".hitung")).toContainText("naik");
  expect(await panel.locator(".sorot").count()).toBeGreaterThanOrEqual(3);
  expect(await panel.locator(".kartu").count()).toBeGreaterThanOrEqual(21);
  await expect(page.locator("footer")).toContainText("PIHPS Nasional – Bank Indonesia");
  await page.locator("#grafik-wilayah").scrollIntoViewIfNeeded();
  await expect(page.locator("#grafik-wilayah canvas")).toBeVisible();
  await page.getByRole("tab", { name: "Semua, bulanan" }).click();
  await expect(page.locator("#ket-grafik")).toContainText("rata-rata bulanan");
  await tanpaLuberHorizontal(page);
  expect(errs).toEqual([]);
});

test("ganti jenis pasar langsung menampilkan panel yang sudah dirender", async ({ page }) => {
  const errs = pantauGalat(page);
  await page.goto("./");
  const harga = () => page.locator(".panel-pasar:not([hidden]) .kartu__harga").first().textContent();
  const hargaAwal = await harga();
  await page.selectOption("#pilih-pasar", "4");
  await expect(page.locator('.panel-pasar[data-pasar="4"]')).toBeVisible();
  await expect(page.locator('.panel-pasar[data-pasar="1"]')).toBeHidden();
  expect(await harga()).not.toBe(hargaAwal);
  const judulBaru = await page.locator('.panel-pasar[data-pasar="4"]').getAttribute("data-judul");
  expect(judulBaru).toBeTruthy();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(judulBaru!);
  expect(errs).toEqual([]);
});

test("pilih wilayah membuka halaman provinsi dengan perbandingan nasional", async ({ page }) => {
  await page.goto("./");
  const opsi = page.locator("#pilih-wilayah optgroup[label='Provinsi'] option").first();
  const kode = await opsi.getAttribute("value");
  const nama = (await opsi.textContent())!.replace(" (data lama)", "");
  await page.selectOption("#pilih-wilayah", kode!);
  await expect(page).toHaveURL(new RegExp(`/wilayah/${kode}/$`));
  await expect(page.locator(".kicker").first()).toContainText(nama);
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await expect(page.locator(".panel-pasar:not([hidden]) .banding").first()).toContainText("nasional");
});

test("halaman komoditas: rantai pasok, tren, provinsi", async ({ page }) => {
  const errs = pantauGalat(page);
  await page.goto("./komoditas/com_13/");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Harga Cabai Merah Besar");
  await expect(page.getByRole("heading", { name: "Dari produsen sampai ke pembeli" })).toBeVisible();
  await page.locator("#grafik-tren").scrollIntoViewIfNeeded();
  await expect(page.locator("#grafik-tren canvas")).toBeVisible();
  await expect(page.locator("#judul-prov")).toBeVisible();
  await tanpaLuberHorizontal(page);
  expect(errs).toEqual([]);
});

test("peta: SVG tanpa distorsi, warna vs nasional, parameter URL, tabel", async ({ page }) => {
  const errs = pantauGalat(page);
  await page.goto("./peta/?k=com_13&p=pasar_modern");
  const svg = page.locator("#peta-svg svg");
  await expect(svg).toBeVisible();
  await expect(page.locator("#peta-svg path.prov")).toHaveCount(34);
  const box = (await svg.boundingBox())!;
  expect(box.width / box.height, "rasio peta Indonesia ±2,7 (tidak direntang)").toBeGreaterThan(2.5);
  expect(box.width / box.height).toBeLessThan(2.9);
  await expect(page.locator("#peta-komoditas")).toHaveValue("com_13");
  await expect(page.locator("#peta-pasar")).toHaveValue("pasar_modern");
  await expect(page.locator("#peta-sorot")).toContainText("Termahal");
  await expect(page.locator("#peta-sorot")).toContainText("Rata-rata nasional");
  await expect(page.locator(".penanda-peta--mahal")).toHaveCount(1);
  await expect(page.locator("#peta-legenda .legenda__item")).toHaveCount(5);
  await expect(page.locator("#peta-tabel tbody tr").first()).toBeVisible();
  // ketuk/klik provinsi berwarna -> angka tampil
  await page.locator("#peta-svg path.prov:not(.k-na)").first().click({ force: true });
  await expect(page.locator("#peta-tip")).toBeVisible();
  await expect(page.locator("#peta-tip")).toContainText("Rp");
  await page.selectOption("#peta-komoditas", "com_1");
  await expect(page).toHaveURL(/k=com_1&/);
  await page.selectOption("#peta-pasar", "pasar_tradisional");
  await expect(page).toHaveURL(/p=pasar_tradisional/);
  await tanpaLuberHorizontal(page);
  expect(errs).toEqual([]);
});

test("halaman statis lain tidak meluber dan tanpa galat", async ({ page }) => {
  const errs = pantauGalat(page);
  for (const path of ["./tentang/", "./komoditas/", "./wilayah/", "./jelajahi/"]) {
    await page.goto(path);
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await tanpaLuberHorizontal(page);
  }
  expect(errs).toEqual([]);
});

// Butuh akses ke jsDelivr & extensions.duckdb.org (jalur produksi). Lewati di lingkungan
// tanpa internet dengan E2E_OFFLINE=1.
test("jelajahi: DuckDB-WASM menjalankan SQL atas Parquet", async ({ page }) => {
  test.skip(!!process.env.E2E_OFFLINE, "butuh akses CDN DuckDB");
  test.setTimeout(120_000);
  const errs = pantauGalat(page);
  await page.goto("./jelajahi/");
  await page.getByRole("button", { name: "Mulai & jalankan" }).click();
  await expect(page.locator("#hasil table")).toBeVisible({ timeout: 90_000 });
  await expect(page.locator("#hasil table tbody tr").first()).toBeVisible();
  await page.getByRole("button", { name: "Cabai rawit merah per bulan" }).click();
  await expect(page.locator("#grafik-hasil canvas")).toBeVisible();
  await page.fill("#sql", "select count(*) as n from harga where is_outlier");
  await page.getByRole("button", { name: "Jalankan" }).click();
  await expect(page.locator("#hasil table td").first()).toHaveText(/^\d/);
  await page.fill("#sql", "select * from tabel_tidak_ada");
  await page.getByRole("button", { name: "Jalankan" }).click();
  await expect(page.locator("#hasil [role=alert]")).toContainText("tabel_tidak_ada");
  expect(errs.filter((e) => !e.includes("tabel_tidak_ada"))).toEqual([]);
});
