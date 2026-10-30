import { defineConfig, devices } from "@playwright/test";
import { fileURLToPath } from "node:url";
import path from "node:path";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(HERE, "..");

const IS_CI = !!process.env.CI;
const PORT = Number(process.env.E2E_PORT || 4173);
const API_PORT = Number(process.env.E2E_API_PORT || 8001);
export const BASE_URL = process.env.E2E_BASE_URL || `http://127.0.0.1:${PORT}`;

const PY = process.platform === "win32"
  ? path.join(ROOT, ".venv", "Scripts", "python.exe")
  : path.join(ROOT, ".venv", "bin", "python");

// A dedicated SQLite file and media root: the suite must never touch a developer's database or uploads.
const E2E_ENV = {
  ...process.env,
  DJANGO_DEBUG: "true",
  // Empty, so a developer's Postgres settings can never make the seed run against their own database.
  POSTGRES_DB: "",
  SQLITE_PATH: path.join(HERE, ".e2e-db.sqlite3"),
  MEDIA_ROOT: path.join(HERE, ".e2e-media"),
  // generate_folder_tree writes into this directory; without the override the seed rewrites the repository's own copy.
  COMPLIANCE_TREE_ROOT: path.join(HERE, ".e2e-tree"),
  // The production login throttle (8/min) would reject valid sign-ins mid-run.
  THROTTLE_LOGIN: "1000/min",
  THROTTLE_ANON: "1000/min",
  THROTTLE_MFA: "1000/min",
  THROTTLE_QUESTIONNAIRE: "1000/min",
  // Passkeys need a domain as relying-party id, not an address: the passkey spec drives the SPA at
  // http://localhost:<port>, everything else at 127.0.0.1. Both are trusted origins.
  WEBAUTHN_RP_ID: "localhost",
  WEBAUTHN_ORIGINS: `http://localhost:${PORT}`,
  DJANGO_ALLOWED_HOSTS: "localhost,127.0.0.1",
  CSRF_TRUSTED_ORIGINS: `${BASE_URL},http://localhost:${PORT}`,
  PYTHONUTF8: "1",
  AUTH_TRANSPORT: process.env.E2E_TRANSPORT || "header",
  // Must match the passwords in fixtures.js (the demo seed generates one otherwise).
  DEMO_PASSWORD: "DemoPass123!",
  AUTH_COOKIE_SECURE: "false",
};

// Every run starts from an empty database: several specs record decisions, so a reused one fails on the second run.
const RESET =
  `"${PY}" -c "import os,shutil,pathlib;` +
  `pathlib.Path(os.environ['SQLITE_PATH']).unlink(missing_ok=True);` +
  `shutil.rmtree(os.environ['MEDIA_ROOT'],ignore_errors=True);` +
  `shutil.rmtree(os.environ['COMPLIANCE_TREE_ROOT'],ignore_errors=True)"`;

const SEED = [
  RESET,
  ...[
    "manage.py migrate --noinput",
    "manage.py seed_frameworks --with-folders",
    "manage.py generate_folder_tree",
    "manage.py bootstrap_demo",
  ].map((c) => `"${PY}" ${c}`),
].join(" && ");

export default defineConfig({
  testDir: "./tests",
  outputDir: "./.results",
  // The specs share one seeded database, so they run serially.
  workers: 1,
  fullyParallel: false,
  forbidOnly: IS_CI,
  retries: IS_CI ? 1 : 0,
  timeout: 45_000,
  expect: { timeout: 10_000 },
  reporter: IS_CI
    ? [["list"], ["html", { open: "never", outputFolder: "./.report" }], ["github"]]
    : [["list"], ["html", { open: "never", outputFolder: "./.report" }]],
  use: {
    baseURL: BASE_URL,
    viewport: { width: 1440, height: 900 },
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "off",
    // framer-motion honours prefers-reduced-motion, which makes assertions about post-transition state deterministic.
    reducedMotion: "reduce",
  },
  projects: [
    { name: "setup", testMatch: /auth\.setup\.js/ },
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"], storageState: "./.auth/admin.json" },
      dependencies: ["setup"],
      testIgnore: /screenshots\.spec\.js/,
    },
    // Opt-in (`npm run shots`): it writes PNGs into the repository, so it must never run as part of `npm test`.
    ...(process.env.SHOOT
      ? [{
          name: "screenshots",
          use: { ...devices["Desktop Chrome"], storageState: "./.auth/admin.json", deviceScaleFactor: 2 },
          dependencies: ["setup"],
          testMatch: /screenshots\.spec\.js/,
        }]
      : []),
  ],
  webServer: [
    {
      command: `${SEED} && "${PY}" manage.py runserver 127.0.0.1:${API_PORT} --noreload`,
      cwd: path.join(ROOT, "backend"),
      url: `http://127.0.0.1:${API_PORT}/api/health/`,
      env: E2E_ENV,
      reuseExistingServer: false,
      timeout: 240_000,
      stdout: "pipe",
      stderr: "pipe",
    },
    {
      // The built SPA through `vite preview`, not the dev server, so a bundling or minification failure shows up here.
      command: `npm run build && npx vite preview --port ${PORT} --strictPort --host 127.0.0.1`,
      cwd: path.join(ROOT, "frontend"),
      url: BASE_URL,
      env: { ...process.env, E2E_API_PORT: String(API_PORT) },
      reuseExistingServer: false,
      timeout: 240_000,
      stdout: "pipe",
      stderr: "pipe",
    },
  ],
});
