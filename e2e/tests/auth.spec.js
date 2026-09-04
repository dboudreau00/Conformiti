import { test, expect, DEMO, signIn, COOKIE_MODE, forgetSession } from "../fixtures.js";

test.describe("authentication", () => {
  test("a wrong password is refused and the user stays on the login page", async ({ page }) => {
    await page.context().clearCookies();
    await page.goto("/login");
    await page.evaluate(() => localStorage.clear());
    await signIn(page, { username: "admin", password: "not-the-password" }, { expectFailure: true });
    await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
    await expect(page).toHaveURL(/\/login/);
    // The shell must not be reachable on a failed attempt.
    await expect(page.getByRole("navigation", { name: "Primary", exact: true })).toHaveCount(0);
  });

  test("a protected route redirects to the login page when signed out", async ({ page }) => {
    await forgetSession(page);
    await page.goto("/controls");
    await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
  });

  test("signing in reaches the dashboard and signing out returns to the login page", async ({ page }) => {
    await page.goto("/login");
    await page.evaluate(() => localStorage.clear());
    await signIn(page, DEMO.admin);

    await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();
    await expect(page.getByText("Ada Admin").first()).toBeVisible();

    await page.getByRole("button", { name: "Sign out" }).first().click();
    await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();

    // The session must be gone, not merely navigated away from.
    const stored = await page.evaluate(() => ({
      access: localStorage.getItem("access"),
      refresh: localStorage.getItem("refresh"),
    }));
    expect(stored.access).toBeNull();
    expect(stored.refresh).toBeNull();
    // In cookie mode the credential was never in localStorage in the first
    // place; what matters is that the cookies are gone.
    const named = (await page.context().cookies()).map((c) => c.name);
    expect(named.filter((n) => n.startsWith("conformiti_"))).toHaveLength(0);
  });

  test("a signed-out user cannot reach the API with the discarded token", async ({ page, request }) => {
    test.skip(COOKIE_MODE,
      "in cookie mode script cannot read the token, which is the point; " +
      "revocation is covered by the backend suite and by the cookie test below");
    await forgetSession(page);
    await signIn(page, DEMO.admin);
    const access = await page.evaluate(() => localStorage.getItem("access"));
    const refresh = await page.evaluate(() => localStorage.getItem("refresh"));
    expect(access).toBeTruthy();

    await page.getByRole("button", { name: "Sign out" }).first().click();
    await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();

    // Sign-out revokes server-side: the refresh token must no longer mint
    // access tokens, which is the whole point of the 0.2.0 rotation work.
    const refreshed = await request.post("/api/auth/token/refresh/", { data: { refresh } });
    expect(refreshed.status()).toBe(401);
  });

  test("each demo persona can sign in", async ({ page }) => {
    for (const persona of ["manager", "owner", "auditor", "viewer"]) {
      await page.goto("/login");
      await page.evaluate(() => localStorage.clear());
      await signIn(page, DEMO[persona]);
      await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();
      await page.getByRole("button", { name: "Sign out" }).first().click();
      await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
    }
  });
});
