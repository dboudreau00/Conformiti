import { test, expect, expectBrowserError, open, topHeading } from "../fixtures.js";

test.describe("when the account lookup fails", () => {
  test("the dashboard says so and Try again recovers, instead of waiting for ever", async ({ page }) => {
    expectBrowserError(page, /status of 500/);
    let failing = true;
    await page.route("**/api/users/me/", (route) => {
      if (!failing) return route.continue();
      return route.fulfill({ status: 500, contentType: "application/json", body: "{}" });
    });
    await page.goto("/");
    await expect(page.getByText("Your account could not be loaded")).toBeVisible();
    await expect(page.getByText("Loading dashboard…")).toHaveCount(0);

    failing = false;
    await page.getByRole("button", { name: "Try again" }).click();
    await expect(topHeading(page, "Dashboard")).toBeVisible();
    await expect(page.getByText(/^(Readiness score|Overall readiness)$/)).toBeVisible();
    await expect(page.getByText("Your account could not be loaded")).toHaveCount(0);
  });
});

test.describe("the workspace switcher", () => {
  test("follows the pages of the list instead of stopping at the first", async ({ page }) => {
    const rows = (from, to) => Array.from({ length: to - from + 1 }, (_, i) => ({
      id: 500 + from + i, name: `Client ${from + i}`, slug: `client-${from + i}`, is_active: true, users: 1,
    }));
    // DRF names the next page by an absolute address, on the origin the suite runs against.
    const origin = new URL(test.info().project.use.baseURL).origin;
    await page.route(/\/api\/workspaces\/(\?page=2)?$/, (route) => {
      if (route.request().method() !== "GET") return route.continue();
      const second = route.request().url().includes("page=2");
      return route.fulfill({
        json: second
          ? { count: 60, next: null, previous: null, results: rows(51, 60) }
          : { count: 60, next: `${origin}/api/workspaces/?page=2`, previous: null, results: rows(1, 50) },
      });
    });
    await open(page, "/settings", "Settings");
    await page.getByRole("navigation", { name: "Settings sections" }).getByRole("button", { name: "Role & access" }).click();
    await expect(page.getByText("Client 1", { exact: true })).toBeVisible();
    await expect(page.getByText("Client 60", { exact: true })).toBeVisible();
  });
});
