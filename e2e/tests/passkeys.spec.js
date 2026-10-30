import { test, expect, DEMO, expectBrowserError, signOut } from "../fixtures.js";

// WebAuthn refuses an IP address as a relying-party id, so this spec drives the SPA at localhost, not
// 127.0.0.1 (WEBAUTHN_RP_ID in playwright.config.js).
const PORT = Number(process.env.E2E_PORT || 4173);
const BASE = `http://localhost:${PORT}`;

function section(page, name) {
  return page.getByRole("navigation", { name: "Settings sections" }).getByRole("button", { name, exact: true });
}

async function signInAt(page, { username, password }) {
  await page.goto(`${BASE}/login`);
  await page.evaluate(() => localStorage.clear());
  await page.locator("#login-username").fill(username);
  await page.locator("#login-password").fill(password);
  await page.getByRole("button", { name: /^sign in$/i }).click();
}

test.describe("passkeys", () => {
  test("a passkey is enrolled in settings and then completes the sign-in", async ({ page }) => {
    const cdp = await page.context().newCDPSession(page);
    await cdp.send("WebAuthn.enable");
    const { authenticatorId } = await cdp.send("WebAuthn.addVirtualAuthenticator", {
      options: {
        protocol: "ctap2", transport: "internal", hasResidentKey: true,
        hasUserVerification: true, isUserVerified: true, automaticPresenceSimulation: true,
      },
    });
    // The second-factor challenge is a deliberate 400 from the token endpoint.
    expectBrowserError(page, /status of 400/);

    try {
      await page.context().clearCookies();
      await signInAt(page, DEMO.owner);
      await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();

      await page.goto(`${BASE}/settings`);
      await section(page, "Security").click();
      await expect(page.getByText("Passkeys and security keys")).toBeVisible();
      await expect(page.getByText("No passkeys enrolled.")).toBeVisible();
      await page.locator("#passkey-name").fill("E2E key");
      // Adding a factor takes the same proof removing one does.
      await page.locator("#passkey-password").fill(DEMO.owner.password);
      await page.getByRole("button", { name: "Add passkey" }).click();
      const list = page.getByRole("list", { name: "Enrolled passkeys" });
      await expect(list.getByText("E2E key")).toBeVisible();
      await expect(list.getByText("Active")).toBeVisible();
      await expect(page.getByText(/Passkey enrolled/)).toBeVisible();

      await signOut(page);
      await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
      await signInAt(page, DEMO.owner);
      await expect(page.getByRole("heading", { name: "Two-factor authentication" })).toBeVisible();
      await expect(page.getByRole("navigation", { name: "Primary", exact: true })).toHaveCount(0);
      await page.getByRole("button", { name: "Use passkey" }).click();
      await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();

      // Remove it again (password-gated), leaving the account as it was.
      await page.goto(`${BASE}/settings`);
      await section(page, "Security").click();
      await expect(list.getByText("E2E key")).toBeVisible();
      await expect(list.getByText(/last used \d{4}-\d{2}-\d{2}/)).toBeVisible();
      await page.locator("#passkey-password").fill(DEMO.owner.password);
      await list.getByRole("button", { name: "Remove" }).click();
      await expect(page.getByText("No passkeys enrolled.")).toBeVisible();
    } finally {
      await cdp.send("WebAuthn.removeVirtualAuthenticator", { authenticatorId }).catch(() => {});
    }
  });
});
