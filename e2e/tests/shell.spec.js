import { test, expect, topHeading, navLink, open } from "../fixtures.js";

// Route -> the title the shell puts in the top bar for it. Mirrors
// frontend/src/nav.js.
const ROUTES = [
  ["/", "Dashboard"],
  ["/analytics", "Analytics"],
  ["/controls", "Controls"],
  ["/documents", "Documents"],
  ["/users", "Users"],
  ["/user-audit", "User audit"],
  ["/packages", "Audit packages"],
  ["/audit-log", "Audit log"],
  ["/meetings", "Meetings"],
  ["/groups", "Champion groups"],
  ["/risks", "Risk register"],
  ["/jira", "Jira boards"],
  ["/settings", "Account"],
];

test.describe("application shell", () => {
  for (const [path, heading] of ROUTES) {
    test(`${path} renders without a browser error`, async ({ page }) => {
      await open(page, path, heading);
      // The console-error assertion in fixtures.js runs on teardown.
    });
  }

  test("the sidebar links to every route", async ({ page }) => {
    await open(page, "/", "Dashboard");
    for (const [path] of ROUTES) {
      await expect(navLink(page, path)).toHaveCount(1);
    }
  });

  test("navigating by sidebar link changes the page", async ({ page }) => {
    await open(page, "/", "Dashboard");
    await navLink(page, "/risks").click();
    await expect(page).toHaveURL(/\/risks$/);
    await expect(topHeading(page, "Risk register")).toBeVisible();

    await navLink(page, "/controls").click();
    await expect(page).toHaveURL(/\/controls$/);
    await expect(topHeading(page, "Controls")).toBeVisible();
  });

  test("routes retired in earlier releases still resolve", async ({ page }) => {
    await page.goto("/account");
    await expect(page).toHaveURL(/\/settings$/);
    await page.goto("/audit");
    await expect(page).toHaveURL(/\/audit-log$/);
    await page.goto("/no-such-page");
    await expect(page).toHaveURL(/\/$/);
  });

  test("the notification tray opens and lists activity", async ({ page }) => {
    await open(page, "/", "Dashboard");
    const bell = page.getByRole("button", { name: /^Notifications/ });
    await expect(bell).toHaveAttribute("aria-expanded", "false");
    await bell.click();
    await expect(bell).toHaveAttribute("aria-expanded", "true");
    // Each item is actionable and separately dismissable.
    await expect(page.getByRole("button", { name: "Dismiss" }).first()).toBeVisible();
  });

  test("dismissing a notification removes it from the tray", async ({ page }) => {
    await open(page, "/", "Dashboard");
    await page.getByRole("button", { name: /^Notifications/ }).click();
    const dismissals = page.getByRole("button", { name: "Dismiss" });
    const before = await dismissals.count();
    test.skip(before === 0, "no notifications to dismiss");
    await dismissals.first().click();
    await page.waitForLoadState("networkidle");
    await expect(dismissals).toHaveCount(before - 1);
  });
});
