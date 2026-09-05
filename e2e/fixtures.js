import { test as base, expect } from "@playwright/test";

export const DEMO = {
  admin: { username: "admin", password: "DemoPass123!" },
  manager: { username: "mia", password: "DemoPass123!" },
  owner: { username: "owen", password: "DemoPass123!" },
  auditor: { username: "aria", password: "DemoPass123!" },
  viewer: { username: "val", password: "DemoPass123!" },
};

// Noise that is not the application's fault and would otherwise make every
// test flaky. Keep this list short and justified — it is the only way a real
// console error can hide.
const IGNORED = [
  /favicon\.ico/i,
  /ERR_INTERNET_DISCONNECTED/,
  /Download the React DevTools/i,
];

/**
 * The project test object. Identical to Playwright's, plus: any console error
 * or uncaught page exception fails the test.
 *
 * This is not decoration. Two real defects in 0.2.0 — duplicate audit-log
 * facets and four pages silently reading only the first page of a paginated
 * endpoint — surfaced first as console noise during a screenshot run.
 */
const ALLOWED = new WeakMap();

/**
 * Let one test tolerate a specific browser error. Chrome logs a console error
 * for every non-2xx response, so a test that deliberately exercises a refusal
 * path must say so — by pattern, never by switching the check off.
 */
export function expectBrowserError(page, pattern) {
  ALLOWED.set(page, [...(ALLOWED.get(page) || []), pattern]);
}

export const test = base.extend({
  page: async ({ page }, use, testInfo) => {
    const problems = [];
    const allowed = (text) => (ALLOWED.get(page) || []).some((re) => re.test(text));
    page.on("console", (msg) => {
      if (msg.type() !== "error") return;
      const text = msg.text();
      if (IGNORED.some((re) => re.test(text)) || allowed(text)) return;
      problems.push(`console.error: ${text}`);
    });
    page.on("pageerror", (err) => problems.push(`pageerror: ${err.message}`));
    page.on("requestfailed", (req) => {
      const failure = req.failure()?.errorText || "";
      const text = `${req.method()} ${req.url()} — ${failure}`;
      if (IGNORED.some((re) => re.test(req.url()) || re.test(failure)) || allowed(text)) return;
      problems.push(`requestfailed: ${text}`);
    });

    await use(page);
    ALLOWED.delete(page);

    if (problems.length && testInfo.status === testInfo.expectedStatus) {
      throw new Error(
        `The page reported ${problems.length} browser error(s):\n  ${problems.join("\n  ")}`
      );
    }
  },
});

/** Sign in through the real form. Used by the setup project and by any test
 *  that needs a different persona than the stored admin session. */
export async function signIn(page, { username, password }, { expectFailure = false } = {}) {
  await page.goto("/login");
  await page.locator("#login-username").fill(username);
  await page.locator("#login-password").fill(password);
  await page.getByRole("button", { name: /sign in/i }).click();
  if (expectFailure) return;
  await page.waitForURL((url) => !url.pathname.startsWith("/login"), { timeout: 20_000 });
}

/** Which transport the server under test is running. The CI job runs the suite
 *  once per transport, so specs that care must branch rather than assume. */
export const TRANSPORT = process.env.E2E_TRANSPORT === "cookie" ? "cookie" : "header";
export const COOKIE_MODE = TRANSPORT === "cookie";

/** Forget the session completely, whichever transport is live. */
export async function forgetSession(page) {
  await page.goto("/login");
  await page.evaluate(() => localStorage.clear());
  await page.context().clearCookies();
}

/** The caller's access token, or null in cookie mode where script cannot read
 *  it -- which is the entire point of that mode. */
export function accessToken(page) {
  return COOKIE_MODE ? Promise.resolve(null)
                     : page.evaluate(() => localStorage.getItem("access"));
}

/** Wait until the shell has finished its initial data load. */
export async function ready(page) {
  await page.waitForLoadState("networkidle");
}

/**
 * The page title in the top bar. Several screens repeat their title as a panel
 * heading further down, so an unscoped getByRole("heading") is ambiguous.
 */
export function topHeading(page, name) {
  return page.getByRole("banner").getByRole("heading", { name, exact: true, level: 1 });
}

/** A sidebar link, addressed by route. Link text carries a live badge count
 *  ("Controls 44"), so matching on the label alone is brittle. */
export function navLink(page, path) {
  return page.getByRole("navigation", { name: "Primary", exact: true }).locator(`a[href="${path}"]`);
}

/** Open a page and wait for it to settle. */
export async function open(page, path, heading) {
  await page.goto(path);
  await expect(topHeading(page, heading)).toBeVisible();
  await page.waitForLoadState("networkidle");
}

export { expect };
