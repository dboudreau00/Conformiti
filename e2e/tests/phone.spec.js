import {
  test, expect, open, topHeading, primaryNav, governanceButton, accountButton, appearanceButton, searchButton,
  openMenu, GOVERNANCE_ROUTES,
} from "../fixtures.js";

/**
 * A phone, 390 by 844. Under 768px the Workspace tabs and the Governance menu
 * do not fit the bar, so they fold into one Menu button that opens a sheet
 * listing every page; search, appearance, notifications and the account menu
 * stay on the bar and open as full-width sheets of their own.
 */
const PHONE = { width: 390, height: 844 };

test.use({ viewport: PHONE });

const ALL_PAGES = ["/", "/analytics", "/controls", "/documents", ...GOVERNANCE_ROUTES, "/settings"];

const menuButton = (page) => page.getByRole("banner").getByRole("button", { name: "Menu", exact: true });

/** How far the page itself scrolls sideways. */
function pageOverflow(page) {
  return page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
}

/** How far the top bar's own content runs past its box. */
function barOverflow(page) {
  return page.evaluate(() => {
    const bar = document.querySelector("header");
    return bar.scrollWidth - bar.clientWidth;
  });
}

test.describe("phone width", () => {
  test("the tabs fold into a Menu button, and its sheet lists every page", async ({ page }) => {
    await open(page, "/", "Dashboard");
    const menu = menuButton(page);
    await expect(menu).toBeVisible();
    await expect(menu).toHaveAttribute("aria-expanded", "false");
    // The tabs and the Governance button are not drawn at this width.
    await expect(governanceButton(page)).toHaveCount(0);
    await expect(primaryNav(page).getByRole("link", { name: "Analytics" })).toHaveCount(0);

    await menu.click();
    await expect(menu).toHaveAttribute("aria-expanded", "true");
    const sheet = page.getByRole("group", { name: "Menu", exact: true });
    await expect(sheet).toBeVisible();
    // Three sections: the core has no sections of its own beyond these.
    await expect(sheet.getByRole("heading")).toHaveText(["Workspace", "Governance", "Account"]);
    const links = sheet.getByRole("link");
    await expect(links).toHaveCount(ALL_PAGES.length);
    expect(await links.evaluateAll((els) => els.map((el) => el.getAttribute("href")))).toEqual(ALL_PAGES);
    await expect(sheet.locator('a[href="/"]')).toHaveAttribute("aria-current", "page");

    // The sheet is whole on the screen.
    await expect.poll(async () => (await sheet.boundingBox()).width).toBeGreaterThan(PHONE.width - 20);
    const box = await sheet.boundingBox();
    expect(box.x).toBeGreaterThanOrEqual(0);
    expect(box.x + box.width).toBeLessThanOrEqual(PHONE.width + 1);
    expect(box.y + box.height).toBeLessThanOrEqual(PHONE.height + 1);
  });

  test("a page chosen in the sheet opens and closes it, and Escape closes it and gives focus back", async ({ page }) => {
    await open(page, "/", "Dashboard");
    const menu = menuButton(page);
    await menu.click();
    const sheet = page.getByRole("group", { name: "Menu", exact: true });
    await sheet.locator('a[href="/risks"]').click();
    await expect(page).toHaveURL(/\/risks$/);
    await expect(topHeading(page, "Risk register")).toBeVisible();
    await expect(menu).toHaveAttribute("aria-expanded", "false");
    await expect(sheet).toHaveCount(0);

    // Open again: the page you are on is the one marked, and focus is on it.
    await menu.click();
    await expect(sheet.locator('a[href="/risks"]')).toHaveAttribute("aria-current", "page");
    await expect(sheet.locator('a[href="/risks"]')).toBeFocused();
    await page.keyboard.press("Escape");
    await expect(sheet).toHaveCount(0);
    await expect(menu).toBeFocused();

    // Keyboard only: Enter on the button opens it and the arrows move down it.
    await page.keyboard.press("Enter");
    await expect(menu).toHaveAttribute("aria-expanded", "true");
    await page.keyboard.press("Home");
    await expect(sheet.locator('a[href="/"]')).toBeFocused();
    await page.keyboard.press("ArrowDown");
    await expect(sheet.locator('a[href="/analytics"]')).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(page).toHaveURL(/\/analytics$/);
    await expect(topHeading(page, "Analytics")).toBeVisible();
  });

  test("search, appearance, notifications and the account menu each open whole on the screen", async ({ page }) => {
    await open(page, "/", "Dashboard");
    const within = (what, box) => {
      expect(box.x, `${what} starts left of the screen`).toBeGreaterThanOrEqual(0);
      expect(box.x + box.width, `${what} runs past the right edge`).toBeLessThanOrEqual(PHONE.width + 1);
      expect(box.y + box.height, `${what} runs past the bottom`).toBeLessThanOrEqual(PHONE.height + 1);
    };
    for (const [what, button] of [
      ["the Appearance panel", appearanceButton(page)],
      ["the notification tray", page.getByRole("button", { name: /^Notifications/ })],
      ["the account menu", accountButton(page)],
    ]) {
      await openMenu(button);
      const panel = page.locator(`[id="${await button.getAttribute("aria-controls")}"]`);
      await expect(panel).toBeVisible();
      await expect.poll(async () => (await panel.boundingBox()).width).toBeGreaterThan(PHONE.width - 30);
      within(what, await panel.boundingBox());
      await page.keyboard.press("Escape");
      await expect(panel).toHaveCount(0);
    }

    await searchButton(page).click();
    const palette = page.getByRole("dialog", { name: "Jump to" });
    await expect(palette).toBeVisible();
    await expect(palette.getByRole("combobox")).toBeFocused();
    within("the search palette", await palette.boundingBox());
    await page.keyboard.press("Escape");
    await expect(palette).toBeHidden();
  });

  test("the bar and the dashboard do not scroll sideways", async ({ page }) => {
    await open(page, "/", "Dashboard");
    // The atlas is requested beside the rest: it must have drawn before the
    // page's width is read.
    await expect(page.getByRole("group", { name: /controls grouped by framework/ }).getByRole("button").first()).toBeVisible();
    expect(await barOverflow(page)).toBeLessThanOrEqual(0);
    expect(await pageOverflow(page)).toBeLessThanOrEqual(1);
    for (const [what, control] of [
      ["the Menu button", menuButton(page)],
      ["the search button", searchButton(page)],
      ["the Appearance button", appearanceButton(page)],
      ["the notification bell", page.getByRole("button", { name: /^Notifications/ })],
      ["the account button", accountButton(page)],
    ]) {
      await expect(control, `${what} is on the bar`).toBeVisible();
      const box = await control.boundingBox();
      expect(box.x, `${what} starts left of the screen`).toBeGreaterThanOrEqual(0);
      expect(box.x + box.width, `${what} runs past the right edge`).toBeLessThanOrEqual(PHONE.width + 1);
    }
  });

  // The bar's own width, on every page. The pages' own layouts are another
  // matter: Users, Champion groups and the Risk register carry tables wider
  // than a phone and scroll the page sideways, as they did under the old
  // shell, so the page-level check below leaves those three out.
  const OVERFLOWING = new Set(["/users", "/groups", "/risks"]);
  for (const path of ALL_PAGES) {
    test(`${path}: the bar fits${OVERFLOWING.has(path) ? "" : " and the page does not scroll sideways"}`, async ({ page }) => {
      await page.goto(path);
      await expect(page.getByRole("main").getByRole("heading", { level: 1 })).toBeVisible();
      await page.waitForLoadState("networkidle");
      expect(await barOverflow(page)).toBeLessThanOrEqual(0);
      if (!OVERFLOWING.has(path)) expect(await pageOverflow(page)).toBeLessThanOrEqual(1);
    });
  }
});
