// E2E atas hasil build (astro preview). CI: `npx playwright install --with-deps chromium`.
// Lingkungan dengan Chromium terpasang di lokasi lain: set PW_CHROMIUM_PATH.
import { defineConfig, devices } from "@playwright/test";

const executablePath = process.env.PW_CHROMIUM_PATH;
const launchOptions = executablePath ? { executablePath } : {};

export default defineConfig({
  testDir: "tests/e2e",
  timeout: 60_000,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["list"], ["github"]] : "list",
  use: {
    baseURL: `http://localhost:4321${process.env.SITE_BASE ?? ""}/`,
    trace: "retain-on-failure",
  },
  webServer: {
    command: "npx astro preview --port 4321",
    url: `http://localhost:4321${process.env.SITE_BASE ?? ""}/`,
    reuseExistingServer: !process.env.CI,
    timeout: 60_000,
  },
  projects: [
    { name: "hp", use: { ...devices["Pixel 7"], launchOptions } },
    { name: "desktop", use: { ...devices["Desktop Chrome"], viewport: { width: 1280, height: 900 }, launchOptions } },
  ],
});
