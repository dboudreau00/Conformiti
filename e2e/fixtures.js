import { test as base, expect } from "@playwright/test";

export const DEMO = {
  admin: { username: "admin", password: "DemoPass123!" },
  manager: { username: "mia", password: "DemoPass123!" },
  owner: { username: "owen", password: "DemoPass123!" },
  auditor: { username: "aria", password: "DemoPass123!" },
  viewer: { username: "val", password: "DemoPass123!" },
};

// Keep short: this list is the only way a real console error can hide.
const IGNORED = [
  /favicon\.ico/i,
  /ERR_INTERNET_DISCONNECTED/,
  /Download the React DevTools/i,
];

const ALLOWED = new WeakMap();

/** Lets one test tolerate a browser error, by pattern: Chrome logs a console error for every non-2xx response. */
export function expectBrowserError(page, pattern) {
  ALLOWED.set(page, [...(ALLOWED.get(page) || []), pattern]);
}

/** Playwright's test, plus: any console error, uncaught page exception or failed request fails the test. */
export const test = base.extend({
  page: async ({ page }, use, testInfo) => {
    const problems = [];
    const allowed = (text) => (ALLOWED.get(page) || []).some((re) => re.test(text));
    page.on("console", (msg) => {
      if (msg.type() !== "error") return;
      const text = msg.text();
      if (IGNORED.some((re) => re.test(text)) || allowed(text)) return;
      // Chrome's "Failed to load resource" names no URL; its location does.
      const where = msg.location()?.url;
      problems.push(`console.error: ${text}${where ? ` (${where})` : ""}`);
    });
    page.on("pageerror", (err) => problems.push(`pageerror: ${err.message}`));
    page.on("requestfailed", (req) => {
      const failure = req.failure()?.errorText || "";
      const text = `${req.method()} ${req.url()}: ${failure}`;
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

export async function signIn(page, { username, password }, { expectFailure = false } = {}) {
  await page.goto("/login");
  await page.locator("#login-username").fill(username);
  await page.locator("#login-password").fill(password);
  await page.getByRole("button", { name: /sign in/i }).click();
  if (expectFailure) return;
  await page.waitForURL((url) => !url.pathname.startsWith("/login"), { timeout: 20_000 });
}

/** The server's auth transport; CI runs the suite once per transport, so specs that care must branch. */
export const TRANSPORT = process.env.E2E_TRANSPORT === "cookie" ? "cookie" : "header";
export const COOKIE_MODE = TRANSPORT === "cookie";

export async function forgetSession(page) {
  await page.goto("/login");
  await page.evaluate(() => localStorage.clear());
  await page.context().clearCookies();
}

export async function ready(page) {
  await page.waitForLoadState("networkidle");
}

/** The page's <h1>: screens repeat their title as a panel heading, so an unscoped getByRole("heading") is ambiguous. */
export function topHeading(page, name) {
  return page.getByRole("main").getByRole("heading", { name, exact: true, level: 1 });
}

/** Mirrors the "governance" section of frontend/src/nav.js, in the order the menu lists them. */
export const GOVERNANCE_ROUTES = [
  "/users", "/user-audit", "/packages", "/vendors", "/responsibilities",
  "/audit-log", "/meetings", "/groups", "/risks", "/jira",
];

export function primaryNav(page) {
  return page.getByRole("navigation", { name: "Primary", exact: true });
}

export function governanceButton(page) {
  return page.getByRole("button", { name: /^Governance\b/ });
}
export function accountButton(page) {
  return page.getByRole("button", { name: / account menu$/ });
}
export function appearanceButton(page) {
  // The colon matters: the Settings page has an "Appearance" section button too.
  return page.getByRole("button", { name: /^Appearance:/ });
}
export function searchButton(page) {
  return page.getByRole("button", { name: "Jump to a control, document or person" });
}

export async function openMenu(button) {
  if ((await button.getAttribute("aria-expanded")) !== "true") await button.click();
  await expect(button).toHaveAttribute("aria-expanded", "true");
}

/** A top-bar link by route, opening its menu first when it lives in one, hence async:
 *  `await (await navLink(page, p)).click()`. "/" is the Dashboard tab, not the logo (which links to "/" too). */
export async function navLink(page, path) {
  if (path === "/settings") {
    await openMenu(accountButton(page));
    return page.getByRole("menuitem", { name: "Settings", exact: true });
  }
  if (GOVERNANCE_ROUTES.includes(path)) await openMenu(governanceButton(page));
  const links = primaryNav(page).locator(`a[href="${path}"]`);
  return path === "/" ? links.filter({ hasNotText: "Home" }) : links;
}

export async function signOut(page) {
  await openMenu(accountButton(page));
  await page.getByRole("menuitem", { name: "Sign out", exact: true }).click();
}

export async function open(page, path, heading) {
  await page.goto(path);
  await expect(topHeading(page, heading)).toBeVisible();
  await page.waitForLoadState("networkidle");
}

export { expect };
