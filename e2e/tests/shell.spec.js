import {
  test, expect, DEMO, forgetSession, signIn, topHeading, navLink, open, primaryNav, openMenu,
  governanceButton, accountButton, appearanceButton, searchButton, GOVERNANCE_ROUTES,
} from "../fixtures.js";

// Mirrors frontend/src/nav.js: route -> the <h1> the page opens with.
const ROUTES = [
  ["/", "Dashboard"],
  ["/analytics", "Analytics"],
  ["/controls", "Controls"],
  ["/documents", "Documents"],
  ["/users", "Users"],
  ["/user-audit", "User audit"],
  ["/packages", "Audit packages"],
  ["/vendors", "Vendors"],
  ["/responsibilities", "Responsibility matrix"],
  ["/audit-log", "Audit log"],
  ["/meetings", "Meetings"],
  ["/groups", "Champion groups"],
  ["/risks", "Risk register"],
  ["/jira", "Jira boards"],
  ["/settings", "Settings"],
];

test.describe("application shell", () => {
  for (const [path, heading] of ROUTES) {
    test(`${path} renders without a browser error and names itself in the tab`, async ({ page }) => {
      await open(page, path, heading);
      await expect(page).toHaveTitle(`${heading} · Conformiti`);
      // The console-error assertion in fixtures.js runs on teardown.
    });
  }

  test("the top bar links to every route", async ({ page }) => {
    await open(page, "/", "Dashboard");
    for (const [path] of ROUTES) {
      const link = await navLink(page, path);
      await expect(link).toHaveCount(1);
      await expect(link).toBeVisible();
      await page.keyboard.press("Escape");
    }
  });

  test("navigating by top bar link changes the page", async ({ page }) => {
    await open(page, "/", "Dashboard");
    await (await navLink(page, "/risks")).click();
    await expect(page).toHaveURL(/\/risks$/);
    await expect(topHeading(page, "Risk register")).toBeVisible();

    await (await navLink(page, "/controls")).click();
    await expect(page).toHaveURL(/\/controls$/);
    await expect(topHeading(page, "Controls")).toBeVisible();

    await (await navLink(page, "/settings")).click();
    await expect(page).toHaveURL(/\/settings$/);
    await expect(topHeading(page, "Settings")).toBeVisible();
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
    await expect(page.getByRole("button", { name: "Dismiss" }).first()).toBeVisible();
  });

  test("the bell's badge says what its name says, in ink the theme pairs with it", async ({ page }) => {
    // Opening the tray marks everything read, so the count is fed to the page rather than left to the shared database.
    const feed = /\/api\/notifications\/(\?.*)?$/;
    for (const [unread, shown] of [[3, "3"], [12, "12"], [150, "99+"]]) {
      await page.route(feed, (route) => route.fulfill({ json: { results: [], unread } }));
      await open(page, "/", "Dashboard");
      const bell = page.getByRole("button", { name: /^Notifications/ });
      await expect(bell).toHaveAccessibleName(`Notifications, ${shown} unread`);
      const badge = bell.locator("span.tabular");
      await expect(badge).toHaveText(shown);
      const colours = await badge.evaluate((el) => {
        const p = document.createElement("i");
        p.style.color = "rgb(var(--danger-ink))";
        document.body.appendChild(p);
        const expected = getComputedStyle(p).color;
        p.remove();
        return { ink: getComputedStyle(el).color, expected };
      });
      expect(colours.ink).toBe(colours.expected);
      await page.unroute(feed);
    }
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

// The labels the bar shows for the Governance pages; mirrors the "governance" section of frontend/src/nav.js.
const GOVERNANCE_LABELS = {
  "/users": "Users",
  "/user-audit": "User audit",
  "/packages": "Audit packages",
  "/vendors": "Vendors",
  "/responsibilities": "Responsibility matrix",
  "/audit-log": "Audit log",
  "/meetings": "Meetings",
  "/groups": "Champion groups",
  "/risks": "Risks",
  "/jira": "Jira",
};

test.describe("the top bar", () => {
  test("the logo goes home and the bar holds no heading of its own", async ({ page }) => {
    await open(page, "/risks", "Risk register");
    await expect(page.getByRole("banner").getByRole("heading")).toHaveCount(0);
    await primaryNav(page).getByRole("link", { name: "Home" }).click();
    await expect(page).toHaveURL(/\/$/);
    await expect(topHeading(page, "Dashboard")).toBeVisible();
  });

  test("the current tab is marked, and Governance names the page when you are on one of its", async ({ page }) => {
    await open(page, "/controls", "Controls");
    for (const path of ["/", "/analytics", "/controls", "/documents"]) {
      const tab = await navLink(page, path);
      if (path === "/controls") await expect(tab).toHaveAttribute("aria-current", "page");
      else await expect(tab).not.toHaveAttribute("aria-current");
    }
    await expect(governanceButton(page)).toHaveAccessibleName("Governance");

    await open(page, "/risks", "Risk register");
    for (const path of ["/", "/analytics", "/controls", "/documents"]) {
      await expect(await navLink(page, path)).not.toHaveAttribute("aria-current");
    }
    await expect(governanceButton(page)).toHaveAccessibleName(/^Governance\s+Risks$/);
  });

  test("Skip to content is the first tab stop and moves focus to the page without changing the address", async ({ page }) => {
    await open(page, "/", "Dashboard");
    await page.keyboard.press("Tab");
    const skip = page.getByRole("link", { name: "Skip to content" });
    await expect(skip).toBeFocused();
    await expect(skip).toBeVisible();
    await page.keyboard.press("Enter");
    await expect(page.locator("#main")).toBeFocused();
    await expect(page).toHaveURL(/\/$/);
  });

  test("the core has no side menu", async ({ page }) => {
    await open(page, "/", "Dashboard");
    await expect(page.getByRole("complementary")).toHaveCount(0);
  });
});

test.describe("the Governance menu", () => {
  test("opens with all ten pages in order, each named and nothing more", async ({ page }) => {
    await open(page, "/", "Dashboard");
    const button = governanceButton(page);
    await expect(button).toHaveAttribute("aria-expanded", "false");
    await expect(button).not.toHaveAttribute("aria-controls");
    await button.click();
    await expect(button).toHaveAttribute("aria-expanded", "true");

    const panel = page.getByRole("group", { name: "Governance" });
    await expect(panel).toBeVisible();
    expect(await button.getAttribute("aria-controls")).toBe(await panel.getAttribute("id"));
    const links = panel.getByRole("link");
    await expect(links).toHaveCount(GOVERNANCE_ROUTES.length);
    expect(await links.evaluateAll((els) => els.map((el) => el.getAttribute("href")))).toEqual(GOVERNANCE_ROUTES);
    const texts = await links.evaluateAll((els) => els.map((el) => el.textContent.trim()));
    texts.forEach((text, i) => {
      expect(text).toMatch(new RegExp(`^${GOVERNANCE_LABELS[GOVERNANCE_ROUTES[i]]}(\\d+ (in progress|open))?$`));
    });
  });

  test("every page in it opens, and the button then names that page", async ({ page }) => {
    await open(page, "/", "Dashboard");
    for (const path of GOVERNANCE_ROUTES) {
      await (await navLink(page, path)).click();
      await expect(page).toHaveURL(new RegExp(`${path}$`));
      await expect(page.getByRole("main").getByRole("heading", { level: 1 })).toBeVisible();
      await expect(governanceButton(page)).toHaveAttribute("aria-expanded", "false");
      await expect(governanceButton(page)).toHaveAccessibleName(
        new RegExp(`^Governance\\s+${GOVERNANCE_LABELS[path]}$`)
      );
      await openMenu(governanceButton(page));
      await expect(page.getByRole("group", { name: "Governance" }).locator(`a[href="${path}"]`))
        .toHaveAttribute("aria-current", "page");
      await page.keyboard.press("Escape");
    }
  });

  test("the keyboard opens it on the current page, moves by cell and row, and Escape gives focus back", async ({ page }) => {
    await open(page, "/risks", "Risk register");
    const button = governanceButton(page);
    const panel = page.getByRole("group", { name: "Governance" });
    const at = (path) => panel.locator(`a[href="${path}"]`);

    await button.focus();
    await page.keyboard.press("Enter");
    await expect(button).toHaveAttribute("aria-expanded", "true");
    await expect(at("/risks")).toBeFocused();

    // Two columns, so a row down is two cells; Home and End reach the ends.
    await page.keyboard.press("Home");
    await expect(at("/users")).toBeFocused();
    await page.keyboard.press("ArrowRight");
    await expect(at("/user-audit")).toBeFocused();
    await page.keyboard.press("ArrowDown");
    await expect(at("/vendors")).toBeFocused();
    await page.keyboard.press("ArrowLeft");
    await expect(at("/packages")).toBeFocused();
    await page.keyboard.press("End");
    await expect(at("/jira")).toBeFocused();
    await page.keyboard.press("ArrowUp");
    await expect(at("/groups")).toBeFocused();

    await page.keyboard.press("Escape");
    await expect(button).toHaveAttribute("aria-expanded", "false");
    await expect(panel).toHaveCount(0);
    await expect(button).toBeFocused();

    await page.keyboard.press("Enter");
    await page.keyboard.press("End");
    await expect(at("/jira")).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(page).toHaveURL(/\/jira$/);
    await expect(topHeading(page, "Jira boards")).toBeVisible();
  });

  test("a press outside and Tab out of it both close it", async ({ page }) => {
    await open(page, "/", "Dashboard");
    const button = governanceButton(page);
    const panel = page.getByRole("group", { name: "Governance" });

    await button.click();
    await expect(panel).toBeVisible();
    // The panel hangs over the left of the page: press on the right of it, on the page itself.
    await page.mouse.click(1150, 110);
    await expect(panel).toHaveCount(0);
    await expect(button).toHaveAttribute("aria-expanded", "false");

    await button.click();
    await page.keyboard.press("End");
    await page.keyboard.press("Tab");
    await expect(panel).toHaveCount(0);
    await expect(button).toHaveAttribute("aria-expanded", "false");
  });
});

test.describe("the account menu", () => {
  test("holds the person, Settings and Sign out", async ({ page }) => {
    await open(page, "/", "Dashboard");
    const button = accountButton(page);
    await expect(button).toHaveAccessibleName("Ada Admin Administrator account menu");
    await expect(button).toHaveAttribute("aria-haspopup", "menu");
    await expect(button).toHaveAttribute("aria-expanded", "false");
    await button.click();
    await expect(button).toHaveAttribute("aria-expanded", "true");

    const menu = page.getByRole("menu", { name: "Account" });
    await expect(menu).toBeVisible();
    await expect(menu.getByRole("menuitem")).toHaveText(["Settings", "Sign out"]);
    const panel = page.locator(`[id="${await button.getAttribute("aria-controls")}"]`);
    await expect(panel).toContainText("Ada Admin");
    await expect(panel).toContainText("Administrator");

    await menu.getByRole("menuitem", { name: "Settings" }).click();
    await expect(page).toHaveURL(/\/settings$/);
    await expect(topHeading(page, "Settings")).toBeVisible();
    await expect(button).toHaveAttribute("aria-expanded", "false");
    await button.click();
    await expect(page.getByRole("menuitem", { name: "Settings" })).toHaveAttribute("aria-current", "page");
  });

  test("the arrow keys open it and move through it, Escape closes it and Tab leaves it", async ({ page }) => {
    await open(page, "/", "Dashboard");
    const button = accountButton(page);
    const settings = page.getByRole("menuitem", { name: "Settings" });
    const signOut = page.getByRole("menuitem", { name: "Sign out" });

    await button.focus();
    await page.keyboard.press("ArrowDown");
    await expect(button).toHaveAttribute("aria-expanded", "true");
    await expect(settings).toBeFocused();
    await page.keyboard.press("ArrowDown");
    await expect(signOut).toBeFocused();
    await page.keyboard.press("ArrowDown");
    await expect(settings).toBeFocused();
    await page.keyboard.press("ArrowUp");
    await expect(signOut).toBeFocused();
    await page.keyboard.press("Home");
    await expect(settings).toBeFocused();

    await page.keyboard.press("Escape");
    await expect(button).toHaveAttribute("aria-expanded", "false");
    await expect(page.getByRole("menu", { name: "Account" })).toHaveCount(0);
    await expect(button).toBeFocused();

    await page.keyboard.press("ArrowUp");
    await expect(signOut).toBeFocused();
    await page.keyboard.press("Tab");
    await expect(button).toHaveAttribute("aria-expanded", "false");
    await expect(button).toBeFocused();
  });
});

test.describe("the Appearance menu", () => {
  test("offers the packs and the accents, keeps itself open while you choose, and closes on Escape", async ({ page }) => {
    await open(page, "/", "Dashboard");
    const button = appearanceButton(page);
    await expect(button).toHaveAccessibleName("Appearance: Ledger Dark theme pack, Azure accent");
    await button.click();
    const menu = page.getByRole("menu", { name: "Appearance" });
    await expect(menu).toBeVisible();

    const radios = menu.getByRole("menuitemradio");
    await expect(radios).toHaveCount(8);
    await expect(menu.getByRole("menuitemradio", { name: /Ledger Dark/ })).toHaveAttribute("aria-checked", "true");
    await expect(menu.getByRole("menuitemradio", { name: "Azure", exact: true })).toHaveAttribute("aria-checked", "true");

    await menu.getByRole("menuitemradio", { name: /Audit Ledger/ }).click();
    await menu.getByRole("menuitemradio", { name: "Ember", exact: true }).click();
    await expect(menu).toBeVisible();
    await expect(menu.getByRole("menuitemradio", { name: /Audit Ledger/ })).toHaveAttribute("aria-checked", "true");
    await expect(menu.getByRole("menuitemradio", { name: "Ember", exact: true })).toHaveAttribute("aria-checked", "true");
    expect(await page.evaluate(() => document.documentElement.dataset.theme)).toBe("ledger");
    expect(await page.evaluate(() => document.documentElement.dataset.accent)).toBe("ember");
    await expect(button).toHaveAccessibleName("Appearance: Audit Ledger theme pack, Ember accent");

    await page.keyboard.press("Escape");
    await expect(menu).toHaveCount(0);
    await expect(button).toBeFocused();
  });
});

test.describe("an external auditor's top bar", () => {
  test("offers only what the API allows, and has no side menu", async ({ page }) => {
    await forgetSession(page);
    await signIn(page, DEMO.auditor);
    await open(page, "/packages", "Audit packages");

    // Of the four tabs only Documents is theirs; "/" is the logo.
    expect(await primaryNav(page).locator("a").evaluateAll((els) => els.map((el) => el.getAttribute("href"))))
      .toEqual(["/", "/documents"]);
    await governanceButton(page).click();
    expect(await page.getByRole("group", { name: "Governance" }).getByRole("link")
      .evaluateAll((els) => els.map((el) => el.getAttribute("href"))))
      .toEqual(["/user-audit", "/packages", "/audit-log"]);
    await expect(governanceButton(page)).toHaveAccessibleName(/^Governance\s+Audit packages$/);
    await page.keyboard.press("Escape");

    await accountButton(page).click();
    await expect(page.getByRole("menu", { name: "Account" }).getByRole("menuitem")).toHaveText(["Settings", "Sign out"]);
    await page.keyboard.press("Escape");
    await expect(page.getByRole("complementary")).toHaveCount(0);
    await expect(searchButton(page)).toBeVisible();
  });
});
