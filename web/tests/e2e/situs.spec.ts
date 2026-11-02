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

test("beranda: kartu harga nasional, ringkasan, dan grafik", async ({ page }) => {
  const errs = pantauGalat(page);
  await page.goto("./");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Harga pangan hari ini");
  await expect(page.locator(".kartu").first()).toBeVisible();
  expect(await page.locator(".kartu").count()).toBeGreaterThanOrEqual(21);
  await expect(page.locator(".ringkasan")).toContainText("naik");
  await expect(page.locator("footer")).toContainText("PIHPS Nasional – Bank Indonesia");
  await page.locator("#grafik-wilayah").scrollIntoViewIfNeeded();
  await expect(page.locator("#grafik-wilayah canvas")).toBeVisible();
  await tanpaLuberHorizontal(page);
  expect(errs).toEqual([]);
});

test("ganti jenis pasar merender ulang kartu dari JSON serving", async ({ page }) => {
  const errs = pantauGalat(page);
  await page.goto("./");
  const hargaAwal = await page.locator(".kartu__harga").first().textContent();
  const tab = page.getByRole("tab", { name: "Produsen" });
  await tab.click();
  await expect(tab).toHaveAttribute("aria-selected", "true");
  await expect(page.locator(".kartu__harga").first()).not.toHaveText(hargaAwal ?? "");
  expect(errs).toEqual([]);
});

test("pilih wilayah membuka halaman provinsi dengan perbandingan nasional", async ({ page }) => {
  await page.goto("./");
  const opsi = page.locator("#pilih-wilayah optgroup[label='Provinsi'] option").first();
  const kode = await opsi.getAttribute("value");
  await page.selectOption("#pilih-wilayah", kode!);
  await expect(page).toHaveURL(new RegExp(`/wilayah/${kode}/$`));
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Harga pangan di");
  await expect(page.locator(".banding").first()).toContainText("nasional");
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

test("peta: choropleth, parameter URL, dan tabel cadangan", async ({ page }) => {
  const errs = pantauGalat(page);
  await page.goto("./peta/?k=com_13&p=pasar_modern");
  await expect(page.locator("#peta-grafik canvas")).toBeVisible();
  await expect(page.locator("#peta-komoditas")).toHaveValue("com_13");
  await expect(page.getByRole("tab", { name: "Pasar Modern" })).toHaveAttribute("aria-selected", "true");
  await expect(page.locator("#peta-tabel tbody tr").first()).toBeVisible();
  await page.selectOption("#peta-komoditas", "com_1");
  await expect(page).toHaveURL(/k=com_1&/);
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
