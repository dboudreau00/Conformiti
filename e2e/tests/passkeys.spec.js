import { test, expect, DEMO, expectBrowserError } from "../fixtures.js";

// WebAuthn refuses an IP address as a relying-party id, so this spec alone
// drives the built SPA at localhost rather than 127.0.0.1 (the server is told
// so in playwright.config.js). A fresh origin means a fresh sign-in.
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
    // Chrome's virtual authenticator: a CTAP2 platform key that confirms
    // presence and verification on its own.
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

      // Enrol.
      await page.goto(`${BASE}/settings`);
      await section(page, "Security").click();
      await expect(page.getByText("Passkeys and security keys")).toBeVisible();
      await expect(page.getByText("No passkeys enrolled.")).toBeVisible();
      await page.locator("#passkey-name").fill("E2E key");
      await page.getByRole("button", { name: "Add passkey" }).click();
      const list = page.getByRole("list", { name: "Enrolled passkeys" });
      await expect(list.getByText("E2E key")).toBeVisible();
      await expect(list.getByText("Active")).toBeVisible();
      await expect(page.getByText(/Passkey enrolled/)).toBeVisible();

      // Sign out, sign in: the password alone is now a challenge.
      await page.getByRole("button", { name: "Sign out" }).first().click();
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
