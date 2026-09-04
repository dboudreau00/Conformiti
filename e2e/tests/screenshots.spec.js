/**
 * Regenerates the README screenshots from the running application.
 *
 *     cd e2e && npm run shots
 *
 * Opt-in (its own Playwright project) because it writes into the repository.
 * The captures are real screens driven through the real UI — never mock-ups —
 * and they inherit the suite's console-error fixture, so a run that produces a
 * screenshot also proves the screen was error-free when it was taken.
 */
import { test as base, expect } from "@playwright/test";
import { fileURLToPath } from "node:url";
import path from "node:path";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const OUT = path.resolve(HERE, "..", "..", "assets", "screenshots");
const THEME = process.env.SHOT_THEME || "ledger-dark";

const test = base.extend({
  page: async ({ page }, use) => {
    const errors = [];
    page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
    page.on("pageerror", (e) => errors.push(String(e)));
    await page.goto("/");
    await page.evaluate((t) => localStorage.setItem("theme", t), THEME);
    await use(page);
    expect(errors, `screens must be captured clean:\n${errors.join("\n")}`).toEqual([]);
  },
});

async function settle(page, ms = 900) {
  await page.waitForLoadState("networkidle").catch(() => {});
  await page.waitForTimeout(ms);
}

async function shot(page, name) {
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.waitForTimeout(200);
  await page.screenshot({ path: path.join(OUT, `${name}.png`) });
}

test.describe.configure({ mode: "serial" });

test("login", async ({ page, context }) => {
  await context.clearCookies();
  await page.goto("/login");
  await page.evaluate((t) => {
    localStorage.clear();
    localStorage.setItem("theme", t);
  }, THEME);
  await page.reload();
  await settle(page);
  await shot(page, "login");
});

const SIMPLE = [
  ["/", "dashboard", 1500],
  ["/analytics", "analytics", 1200],
  ["/users", "users", 1200],
  ["/user-audit", "access-reviews", 1200],
  ["/packages", "audit-packages", 1500],
  ["/audit-log", "audit-log", 1200],
  ["/meetings", "meetings", 1200],
  ["/groups", "groups", 1200],
  ["/jira", "jira", 1200],
];

for (const [route, name, wait] of SIMPLE) {
  test(name, async ({ page }) => {
    await page.goto(route);
    await settle(page, wait);
    await shot(page, name);
  });
}

test("controls", async ({ page }) => {
  await page.goto("/controls");
  await settle(page, 1600);
  // Scoped to the register: the top bar's theme picker is also an
  // aria-expanded control, and an unscoped .first() opened that instead.
  const row = page.getByRole("main").locator("[aria-expanded]").first();
  if (await row.count()) {
    await row.click().catch(() => {});
    await page.waitForTimeout(900);
  }
  await shot(page, "controls");
});

test("documents", async ({ page }) => {
  await page.goto("/documents");
  await settle(page, 1600);
  for (const label of [/SOC 2/i, /^CC6\b/i, /CC6\.1/i]) {
    const node = page.getByRole("treeitem", { name: label }).first();
    if (await node.count()) {
      await node.click().catch(() => {});
      await page.waitForTimeout(700);
    }
  }
  await settle(page, 700);
  await shot(page, "documents");
});

test("risks", async ({ page }) => {
  await page.goto("/risks");
  await settle(page, 1400);
  const row = page.locator('tbody tr[role="button"]').first();
  if (await row.count()) {
    await row.click().catch(() => {});
    await page.waitForTimeout(900);
  }
  await shot(page, "risks");
});

test("settings", async ({ page }) => {
  await page.goto("/settings");
  await settle(page, 1200);
  const appearance = page
    .getByRole("navigation", { name: "Settings sections" })
    .getByRole("button", { name: "Appearance", exact: true });
  if (await appearance.count()) {
    await appearance.click();
    await page.waitForTimeout(700);
  }
  await shot(page, "settings");
});
