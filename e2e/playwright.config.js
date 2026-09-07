import { defineConfig, devices } from "@playwright/test";
import { fileURLToPath } from "node:url";
import path from "node:path";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(HERE, "..");

// The suite drives the *built* SPA served by `vite preview`, not the dev
// server, so a bundling or minification failure is caught here rather than in
// production. Both servers are started by Playwright unless they are already
// running (locally) — in CI they are always started fresh.
const IS_CI = !!process.env.CI;
const PORT = Number(process.env.E2E_PORT || 4173);
const API_PORT = Number(process.env.E2E_API_PORT || 8001);
export const BASE_URL = process.env.E2E_BASE_URL || `http://127.0.0.1:${PORT}`;

const PY = process.platform === "win32"
  ? path.join(ROOT, ".venv", "Scripts", "python.exe")
  : path.join(ROOT, ".venv", "bin", "python");

// A dedicated SQLite file and media directory so running the suite never
// touches a developer's working database or uploads.
const E2E_ENV = {
  ...process.env,
  DJANGO_DEBUG: "true",
  SQLITE_PATH: path.join(HERE, ".e2e-db.sqlite3"),
  MEDIA_ROOT: path.join(HERE, ".e2e-media"),
  // generate_folder_tree writes a manifest and a README into this directory;
  // without an override the seed rewrites the repository's own copy.
  COMPLIANCE_TREE_ROOT: path.join(HERE, ".e2e-tree"),
  // The suite signs in more often than a human would; the production login
  // throttle (8/min) would start rejecting valid attempts mid-run.
  THROTTLE_LOGIN: "1000/min",
  THROTTLE_ANON: "1000/min",
  THROTTLE_MFA: "1000/min",
  THROTTLE_QUESTIONNAIRE: "1000/min",
  // Passkeys need a relying-party id that is a domain, not an address; the
  // passkey spec therefore drives the SPA at http://localhost:<port> while
  // everything else uses 127.0.0.1. Both are trusted origins.
  WEBAUTHN_RP_ID: "localhost",
  WEBAUTHN_ORIGINS: `http://localhost:${PORT}`,
  DJANGO_ALLOWED_HOSTS: "localhost,127.0.0.1",
  CSRF_TRUSTED_ORIGINS: `${BASE_URL},http://localhost:${PORT}`,
  PYTHONUTF8: "1",
  // Both transports are exercised: this run uses whichever E2E_TRANSPORT
  // says, and the CI job runs the suite twice.
  AUTH_TRANSPORT: process.env.E2E_TRANSPORT || "header",
  // The demo seed generates a password unless one is given; the fixtures
  // in fixtures.js sign in with this one.
  DEMO_PASSWORD: "DemoPass123!",
  AUTH_COOKIE_SECURE: "false",
};

// Every run starts from an empty database. Several specs record decisions and
// mark documents reviewed, so a reused database would fail on the second run
// for reasons that have nothing to do with the code under test.
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
  // Every spec is written to be independent, but they share one seeded
  // database, so writes are serialised to keep runs reproducible.
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
    // framer-motion honours prefers-reduced-motion, which makes assertions
    // about post-transition state deterministic.
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
    // Opt-in only (`npm run shots`): this project writes PNGs into the
    // repository, so it must never run as a side effect of `npm test`.
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
