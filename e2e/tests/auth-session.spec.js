import { test, expect, DEMO, signIn, forgetSession, COOKIE_MODE, topHeading } from "../fixtures.js";

test.describe("a reload after the access cookie lapsed", () => {
  test.skip(!COOKIE_MODE, "the access cookie only exists in cookie mode (E2E_TRANSPORT=cookie)");

  test("AUTH-01: renews through the refresh cookie instead of asking for the password again", async ({ page }) => {
    await forgetSession(page);
    await signIn(page, DEMO.admin);
    await expect(topHeading(page, "Dashboard")).toBeVisible();
    await page.waitForLoadState("networkidle");

    const before = (await page.context().cookies()).find((c) => c.name.endsWith("conformiti_refresh"));
    expect(before, "the refresh cookie is set").toBeTruthy();
    // What the 60-minute Max-Age does: the browser drops the access cookie and keeps the 7-day refresh cookie.
    await page.context().clearCookies({ name: /conformiti_access$/ });
    expect((await page.context().cookies()).some((c) => c.name.endsWith("conformiti_access"))).toBe(false);

    await page.goto("/settings");
    await expect(topHeading(page, "Settings")).toBeVisible();
    await expect(page).not.toHaveURL(/\/login/);

    const after = await page.context().cookies();
    expect(after.some((c) => c.name.endsWith("conformiti_access"))).toBe(true);
    expect(after.find((c) => c.name.endsWith("conformiti_refresh")).value, "the refresh token rotated")
      .not.toBe(before.value);
  });

  test("AUTH-01: the refresh cookie still travels only under its own path", async ({ page }) => {
    await forgetSession(page);
    await signIn(page, DEMO.admin);
    const refresh = (await page.context().cookies()).find((c) => c.name.endsWith("conformiti_refresh"));
    expect(refresh.path).toBe("/api/auth/token/");
  });

  test("AUTH-01: after signing out a reload shows sign-in, not a session", async ({ page }) => {
    await forgetSession(page);
    await signIn(page, DEMO.admin);
    await expect(topHeading(page, "Dashboard")).toBeVisible();
    await page.waitForLoadState("networkidle");
    await page.getByRole("button", { name: / account menu$/ }).click();
    await page.getByRole("menuitem", { name: "Sign out", exact: true }).click();
    await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
    await page.goto("/controls");
    await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
  });

  test("AUTH-01: a visitor with no cookies is sent to sign-in without a console error", async ({ page }) => {
    await forgetSession(page);
    await page.goto("/controls");
    await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
  });
});

test.describe("a second sign-in tab", () => {
  test("WEB-04: a wrong password there leaves the first tab signed in and in its workspace", async ({ page, context }) => {
    await forgetSession(page);
    await signIn(page, DEMO.admin);
    await expect(topHeading(page, "Dashboard")).toBeVisible();
    await page.waitForLoadState("networkidle");
    await page.evaluate(() => localStorage.setItem("workspace", "default"));
    const held = await page.evaluate(() => ({
      access: localStorage.getItem("access"), refresh: localStorage.getItem("refresh"),
    }));

    const other = await context.newPage();
    await other.goto("/login");
    await other.locator("#login-username").fill("admin");
    await other.locator("#login-password").fill("not-the-password");
    await other.getByRole("button", { name: /sign in/i }).click();
    await expect(other.getByText(/incorrect|invalid|no active account/i).first()).toBeVisible();

    const kept = await other.evaluate(() => ({
      access: localStorage.getItem("access"), refresh: localStorage.getItem("refresh"),
      workspace: localStorage.getItem("workspace"),
    }));
    expect(kept.workspace).toBe("default");
    if (!COOKIE_MODE) expect({ access: kept.access, refresh: kept.refresh }).toEqual(held);

    await page.goto("/controls");
    await expect(topHeading(page, "Controls")).toBeVisible();
    await other.close();
  });
});
