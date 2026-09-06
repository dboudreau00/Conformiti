import { test, expect, open, expectBrowserError } from "../fixtures.js";

const SECTIONS = ["Profile", "Appearance", "Security", "Notifications", "Role & access", "About"];

/** The settings sidebar is a plain <nav> of buttons, not a tablist. */
function section(page, name) {
  return page.getByRole("navigation", { name: "Settings sections" })
    .getByRole("button", { name, exact: true });
}

test.describe("account settings", () => {
  test.beforeEach(async ({ page }) => {
    await open(page, "/settings", "Account");
  });

  test("every settings section is reachable", async ({ page }) => {
    for (const name of SECTIONS) {
      await section(page, name).click();
      await expect(section(page, name)).toHaveAttribute("aria-current", "true");
      await expect(page.getByRole("main")).toContainText(name);
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
    await expect(page.getByRole("main")).toContainText("Administrator");
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
    await open(page, "/settings", "Account");
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
    await open(page, "/settings", "Account");
    await section(page, "Security").click();
    await page.waitForLoadState("networkidle");

    // The block renders a loading placeholder first; without this wait the
    // Enable button is simply absent and the test skips itself into silence.
    await expect(page.getByText("Authenticator app").first()).toBeVisible();
    const enable = page.getByRole("button", { name: "Enable", exact: true });
    await expect(enable).toBeVisible();
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
});
