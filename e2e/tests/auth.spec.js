import { test, expect, DEMO, signIn, signOut, accountButton, COOKIE_MODE, forgetSession } from "../fixtures.js";

test.describe("authentication", () => {
  test("a wrong password is refused and the user stays on the login page", async ({ page }) => {
    await page.context().clearCookies();
    await page.goto("/login");
    await page.evaluate(() => localStorage.clear());
    await signIn(page, { username: "admin", password: "not-the-password" }, { expectFailure: true });
    await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
    await expect(page).toHaveURL(/\/login/);
    await expect(page.getByRole("navigation", { name: "Primary", exact: true })).toHaveCount(0);
  });

  test("the sign-in page's shield and wordmark wear the saved accent", async ({ page }) => {
    await forgetSession(page);
    await page.goto("/login");
    await page.evaluate(() => { localStorage.setItem("accent", "ember"); });
    await page.reload();
    await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
    const painted = await page.evaluate(() => {
      const probe = (value) => {
        const el = document.createElement("i");
        el.style.color = value;
        document.body.appendChild(el);
        const out = getComputedStyle(el).color;
        el.remove();
        return out;
      };
      const form = document.querySelector("form");
      const [right, left] = [...form.querySelectorAll("svg path")].slice(0, 2).map((p) => getComputedStyle(p).fill);
      const word = [...form.querySelectorAll("span")].find((s) => s.textContent === "iti");
      return {
        right, left, word: getComputedStyle(word).color,
        accent: probe("rgb(var(--accent))"), deep: probe("rgb(var(--accent-deep))"),
        text: probe("rgb(var(--accent-text, var(--accent)))"),
      };
    });
    expect(painted.right).toBe(painted.accent);
    expect(painted.left).toBe(painted.deep);
    expect(painted.word).toBe(painted.text);
    expect(painted.left).not.toBe(painted.right);
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
    await expect(accountButton(page)).toHaveAccessibleName(/Ada Admin/);

    await signOut(page);
    await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();

    const stored = await page.evaluate(() => ({
      access: localStorage.getItem("access"),
      refresh: localStorage.getItem("refresh"),
    }));
    expect(stored.access).toBeNull();
    expect(stored.refresh).toBeNull();
    // In cookie mode nothing was ever in localStorage; what matters is that the cookies are gone.
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

    await signOut(page);
    await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();

    // Sign-out revokes server-side: the refresh token must no longer mint access tokens.
    const refreshed = await request.post("/api/auth/token/refresh/", { data: { refresh } });
    expect(refreshed.status()).toBe(401);
  });

  test("each demo persona can sign in", async ({ page }) => {
    for (const persona of ["manager", "owner", "auditor", "viewer"]) {
      await page.goto("/login");
      await page.evaluate(() => localStorage.clear());
      await signIn(page, DEMO[persona]);
      const landing = persona === "auditor" ? "Audit packages" : "Dashboard";
      await expect(page.getByRole("heading", { name: landing })).toBeVisible();
      // A request in flight at sign-out is refused and logged as a console error: let the page settle first.
      await page.waitForLoadState("networkidle");
      await signOut(page);
      await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
    }
  });

  test("an auditor at an address the menu never offers is told so, and sent to their packages", async ({ page }) => {
    await page.goto("/login");
    await page.evaluate(() => localStorage.clear());
    await signIn(page, DEMO.auditor);
    await expect(page.getByRole("heading", { name: "Audit packages" })).toBeVisible();
    for (const path of ["/controls", "/risks"]) {
      await page.goto(path);
      await expect(page.getByText("Not available to an auditor account")).toBeVisible();
      await expect(page.getByText("You do not have permission")).toHaveCount(0);
    }
    await page.getByRole("button", { name: "Go to your packages" }).click();
    await expect(page.getByRole("heading", { name: "Audit packages" })).toBeVisible();
    await page.goto("/audit-log");
    await expect(page.getByRole("heading", { name: "Audit log" })).toBeVisible();
    await expect(page.getByText("Not available to an auditor account")).toHaveCount(0);
    await page.waitForLoadState("networkidle");
    await signOut(page);
  });
});
