import { test, expect, open, expectBrowserError, DEMO } from "../fixtures.js";

const SECTIONS = ["Profile", "Appearance", "Security", "Notifications", "Role & access", "About"];

/** The settings sidebar is a plain <nav> of buttons, not a tablist. */
function section(page, name) {
  return page.getByRole("navigation", { name: "Settings sections" })
    .getByRole("button", { name, exact: true });
}

/** The heading an open section starts with. The nav listing every section,
 *  and the card above it naming the user's role, sit inside <main> too, so
 *  text found anywhere in main says nothing about which section rendered. */
function heading(page, name) {
  return page.getByRole("main").getByRole("heading", { name, exact: true, level: 2 });
}

test.describe("account settings", () => {
  test.beforeEach(async ({ page }) => {
    await open(page, "/settings", "Settings");
  });

  test("every settings section is reachable", async ({ page }) => {
    for (const name of SECTIONS) {
      await section(page, name).click();
      await expect(section(page, name)).toHaveAttribute("aria-current", "true");
      await expect(heading(page, name)).toBeVisible();
    }
  });

  test("the profile form saves a change and it survives a reload", async ({ page }) => {
    await section(page, "Profile").click();
    const jobTitle = page.locator("#acct-title");
    const value = "Head of Compliance (e2e)";
    await jobTitle.fill(value);
    await page.getByRole("button", { name: /save changes/i }).click();
    await page.waitForLoadState("networkidle");

    await page.reload();
    await page.waitForLoadState("networkidle");
    await section(page, "Profile").click();
    await expect(page.locator("#acct-title")).toHaveValue(value);
  });

  test("the role section reports the signed-in user's capabilities", async ({ page }) => {
    await section(page, "Role & access").click();
    // The section's own panel: the card above the nav names the role
    // whichever section is open.
    const panel = page.getByRole("main").locator("section")
      .filter({ has: page.getByRole("heading", { name: "Role & access", exact: true, level: 2 }) });
    await expect(panel).toContainText("Administrator");
  });

  test("the digest preference saves and survives a reload", async ({ page }) => {
    await section(page, "Notifications").click();
    const cadence = page.locator("#digest-cadence");
    await expect(cadence).toBeVisible();
    await cadence.selectOption("daily");
    await expect(page.getByText(/daily digest of your tray/)).toBeVisible();
    await expect(page.getByText(/Slack not configured/)).toBeVisible();
    await page.reload();
    await page.waitForLoadState("networkidle");
    await section(page, "Notifications").click();
    await expect(page.locator("#digest-cadence")).toHaveValue("daily");
    await page.locator("#digest-cadence").selectOption("off");
    await expect(page.getByText("Digest emails are off.")).toBeVisible();
  });
});

test.describe("appearance", () => {
  test.beforeEach(async ({ page }) => {
    await open(page, "/settings", "Settings");
    await section(page, "Appearance").click();
  });

  test("every theme pack applies, resolves its tokens and persists", async ({ page }) => {
    const packs = page.getByRole("group", { name: "Theme pack" });
    for (const name of ["Audit Ledger", "Nimbus", "Ledger Dark", "Obsidian"]) {
      const button = packs.getByRole("button", { name: new RegExp(`^${name}`) });
      if (!(await button.count())) continue;
      await button.first().click();
      await page.waitForTimeout(150);
      await expect(button.first()).toHaveAttribute("aria-pressed", "true");
      // A theme that does not resolve its tokens paints nothing.
      const bg = await page.evaluate(() =>
        getComputedStyle(document.documentElement).getPropertyValue("--bg").trim()
      );
      expect(bg, `theme ${name} left --bg unresolved`).toMatch(/^\d+ \d+ \d+$/);
    }

    const chosen = await page.evaluate(() => document.documentElement.dataset.theme);
    await page.reload();
    await page.waitForLoadState("networkidle");
    expect(await page.evaluate(() => document.documentElement.dataset.theme)).toBe(chosen);
  });

  test("each accent pack applies and persists", async ({ page }) => {
    const accents = page.getByRole("group", { name: "Accent pack" });
    for (const accent of ["Pine", "Azure", "Violet", "Ember"]) {
      await accents.getByRole("button", { name: new RegExp(`^${accent}`) }).first().click();
      await page.waitForTimeout(150);
      expect(await page.evaluate(() => document.documentElement.dataset.accent))
        .toBe(accent.toLowerCase());
      const token = await page.evaluate(() =>
        getComputedStyle(document.documentElement).getPropertyValue("--accent").trim()
      );
      expect(token, `accent ${accent} left --accent unresolved`).toMatch(/^\d+ \d+ \d+$/);
    }

    await page.reload();
    await page.waitForLoadState("networkidle");
    expect(await page.evaluate(() => document.documentElement.dataset.accent)).toBe("ember");
  });

  test("the top bar theme menu offers the same packs", async ({ page }) => {
    await page.getByRole("banner").locator('button[aria-haspopup="menu"]').click();
    await expect(page.getByRole("menuitemradio", { name: /Obsidian/ })).toBeVisible();
    await page.getByRole("menuitemradio", { name: /Nimbus/ }).click();
    await page.waitForTimeout(150);
    expect(await page.evaluate(() => document.documentElement.dataset.theme)).toBe("nimbus");
  });
});

test.describe("multi-factor authentication", () => {
  test("enrolment shows a secret and refuses a wrong code", async ({ page }) => {
    await open(page, "/settings", "Settings");
    await section(page, "Security").click();
    await page.waitForLoadState("networkidle");

    // The block renders a loading placeholder first; without this wait the
    // Enable button is simply absent and the test skips itself into silence.
    await expect(page.getByText("Authenticator app").first()).toBeVisible();
    const enable = page.getByRole("button", { name: "Enable", exact: true });
    await expect(enable).toBeVisible();

    // Enrolling a factor takes the same proof removing one does (0.9.5f):
    // a session somebody else is holding must not be able to make their
    // authenticator the one this account needs. Adding a passkey has asked
    // since 0.9.5; the authenticator app asked for nothing.
    await expect(page.locator("#mfa-enable-password")).toBeVisible();
    await page.locator("#mfa-enable-password").fill(DEMO.admin.password);
    await enable.click();
    await page.waitForLoadState("networkidle");

    // The enrolment URI must be shown before any code is accepted.
    await expect(page.locator("#mfa-uri")).toHaveValue(/^otpauth:\/\/totp\//);

    // Chrome logs a console error for the 400 this deliberately provokes.
    expectBrowserError(page, /status of 400/);
    await page.locator("#mfa-code").fill("000000");
    await page.getByRole("button", { name: /verify & turn on/i }).click();
    await page.waitForLoadState("networkidle");
    await expect(page.getByText(/code isn.t valid/i).first()).toBeVisible();

    // A refused code must leave the device disabled, not half-enrolled.
    await page.reload();
    await page.waitForLoadState("networkidle");
    await section(page, "Security").click();
    await expect(page.getByRole("button", { name: "Enable", exact: true })).toBeVisible();
  });

  test("enrolment without the password is refused", async ({ page }) => {
    await open(page, "/settings", "Settings");
    await section(page, "Security").click();
    await expect(page.getByText("Authenticator app").first()).toBeVisible();

    expectBrowserError(page, /status of 403/);
    await page.getByRole("button", { name: "Enable", exact: true }).click();
    await page.waitForLoadState("networkidle");

    await expect(page.locator("#mfa-uri")).toHaveCount(0);
    await expect(page.getByText(/confirm your password/i).first()).toBeVisible();
  });
});

test.describe("workspace chat channels", () => {
  /** Click Save and wait for the PATCH itself to come back.
   *  `waitForLoadState("networkidle")` is not enough here: the page is
   *  already idle when the click happens, so it can resolve before the
   *  request is even sent, and the reload that follows cancels it. */
  async function save(page) {
    const patched = page.waitForResponse((r) =>
      r.request().method() === "PATCH" && r.url().includes("/api/workspaces/"));
    await page.getByRole("button", { name: "Save", exact: true }).click();
    return patched;
  }

  /** The webhook URL is a credential and is never returned by the API, so the
   *  box is always empty on load and says whether one is configured. That
   *  makes "saved the form with an empty box" ambiguous, and getting it wrong
   *  deletes a working channel (REVIEW_095.md, S-1). */
  test("a saved webhook is shown as configured, never echoed, and survives an unrelated save",
    async ({ page }) => {
      await open(page, "/settings", "Settings");
      await section(page, "Role & access").click();

      const slack = page.locator("#workspace-slack");
      await expect(slack).toBeVisible();
      await slack.fill("https://hooks.slack.com/services/T000/B000/e2esecret");
      expect((await save(page)).status()).toBe(200);

      // Configured, and the URL is not on the page anywhere.
      await page.reload();
      await page.waitForLoadState("networkidle");
      await section(page, "Role & access").click();
      await expect(page.getByText(/Configured\. Type a new URL to replace it\./).first())
        .toBeVisible();
      await expect(slack).toHaveValue("");
      expect(await page.content()).not.toContain("e2esecret");

      // Saving the reminder address with the webhook box untouched must not
      // clear the channel.
      await page.locator("#workspace-inbox").fill("grc@e2e.example");
      expect((await save(page)).status()).toBe(200);
      await page.reload();
      await page.waitForLoadState("networkidle");
      await section(page, "Role & access").click();
      await expect(page.getByText(/Configured\. Type a new URL to replace it\./).first())
        .toBeVisible();

      // Remove is the one thing that clears it.
      const removed = page.waitForResponse((r) =>
        r.request().method() === "PATCH" && r.url().includes("/api/workspaces/"));
      await page.getByRole("button", { name: "Remove", exact: true }).first().click();
      expect((await removed).status()).toBe(200);
      await expect(page.getByText(/Configured\. Type a new URL to replace it\./))
        .toHaveCount(0);
    });

  test("a webhook on someone else's host is refused", async ({ page }) => {
    await open(page, "/settings", "Settings");
    await section(page, "Role & access").click();
    expectBrowserError(page, /status of 400/);
    await page.locator("#workspace-slack").fill("https://hooks.slack.com.attacker.example/x");
    expect((await save(page)).status()).toBe(400);
    await expect(page.getByText(/Expected one of/i).first()).toBeVisible();
  });
});
