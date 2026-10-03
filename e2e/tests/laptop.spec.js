/**
 * The three screens that must fit a 1366 by 768 laptop.
 *
 * The access review's decision and justification columns, the document table
 * and the vendor responsibility matrix must not run past the right edge: the
 * columns a reviewer uses on every row are the ones that would go off screen.
 *
 * Each of those tables sits in a sideways scroller of its own, so the page
 * never scrolls even while columns are off screen: they slide out of sight
 * inside the panel instead. The page staying still proves nothing on its own.
 * Each test therefore opens its screen until the table itself is rendered,
 * then measures how far the table reaches and where a control used on every
 * row sits, against the panel holding them and the window's width.
 */
import {
  test, expect, open, openMenu, governanceButton, accountButton, appearanceButton, searchButton,
} from "../fixtures.js";

const LAPTOP = { width: 1366, height: 768 };

test.use({ viewport: LAPTOP });

/** How far the page itself scrolls sideways. When it does, the top bar and
 *  the page travel with it and nothing stays where the eye left it. */
async function pageOverflow(page) {
  return page.evaluate(() => {
    const d = document.documentElement;
    return d.scrollWidth - d.clientWidth;
  });
}

/**
 * Where a row's control ends and how far its table reaches, beside the right
 * edge of the panel holding both and the width of the window.
 *
 * The table's reach is read from the nearest ancestor that scrolls sideways,
 * or from the panel when nothing inside it does. Its scrollWidth counts the
 * columns that run past its box; no bounding box shows them, because they
 * scroll out of sight instead of pushing anything outward.
 */
function reach(control) {
  return control.evaluate((el) => {
    const panel = el.closest("section");
    if (!panel) throw new Error("the control is not inside a panel (<section>)");
    let frame = el.parentElement;
    while (frame !== panel && !/auto|scroll/.test(getComputedStyle(frame).overflowX)) {
      frame = frame.parentElement;
    }
    const inner = (node) => node.getBoundingClientRect().left + node.clientLeft;
    return {
      table: inner(frame) + frame.scrollWidth,
      control: el.getBoundingClientRect().right,
      panel: inner(panel) + panel.clientWidth,
      viewport: document.documentElement.clientWidth,
    };
  });
}

/** The control is rendered, and neither it nor its table runs past the panel
 *  or the window. One pixel of slack: layout rounds to whole pixels. */
async function expectOnScreen(page, what, control) {
  await expect(control).toBeVisible();
  const r = await reach(control);
  expect(r.table, `the table holding ${what} runs past its panel`).toBeLessThanOrEqual(r.panel + 1);
  expect(r.control, `${what} sits past the edge of its panel`).toBeLessThanOrEqual(r.panel + 1);
  expect(r.table, `the table holding ${what} runs past the window`).toBeLessThanOrEqual(r.viewport + 1);
  expect(r.control, `${what} sits past the edge of the window`).toBeLessThanOrEqual(r.viewport + 1);
  expect(await pageOverflow(page)).toBeLessThanOrEqual(1);
}

test.describe("laptop width", () => {
  test("the access review keeps the decision and the justification on screen", async ({ page }) => {
    await open(page, "/user-audit", "User audit");
    // The first row's own controls. The review picker above the grid is a
    // control in main as well, and it sits at the left whatever the grid does.
    await expectOnScreen(page, "the decision",
      page.getByRole("radiogroup", { name: /^Decision for / }).first());
    await expectOnScreen(page, "the justification",
      page.getByRole("textbox", { name: /^Notes for / }).first());
  });

  test("the document table keeps its row actions on screen", async ({ page }) => {
    await open(page, "/documents", "Documents");
    // No folder is selected on arrival, so there is no table until one is.
    for (const label of [/SOC 2/i, /^CC6\b/i, /CC6\.1/i]) {
      await page.getByRole("treeitem", { name: label }).first().click();
    }
    await expectOnScreen(page, "the row actions",
      page.getByRole("button", { name: /^Actions for / }).first());
  });

  test("the vendor responsibility matrix keeps its statements on screen", async ({ page }) => {
    await open(page, "/vendors", "Vendors");
    // A vendor opens on its overview; the matrix is a tab of its own.
    await page.getByRole("button", { name: /Amazon Web Services/ }).click();
    await expect(page.getByRole("heading", { name: "Amazon Web Services" })).toBeVisible();
    await page.getByRole("main").getByRole("tab", { name: "Responsibility matrix", exact: true }).click();
    await expect(page.getByRole("heading", { name: "Shared responsibility matrix" })).toBeVisible();
    await expectOnScreen(page, "the responsibility",
      page.getByRole("group", { name: /^Responsibility for / }).first());
    await expectOnScreen(page, "the statement",
      page.getByRole("textbox", { name: /^We do for / }).first());
  });

  // Not one of the three. Its matrix is wider than its column at this width
  // and scrolls inside its panel, which the release does not claim to fix;
  // what it must not do is take the page sideways with it.
  test("the RACI matrix does not scroll the page sideways", async ({ page }) => {
    await open(page, "/responsibilities", "Responsibility matrix");
    await expect(page.getByRole("main").getByRole("table").first()).toBeVisible();
    expect(await pageOverflow(page)).toBeLessThanOrEqual(1);
  });
});

/** The panels (<section>) of a page that reach past the window's right edge. */
function panelsPastTheEdge(page) {
  return page.evaluate(() => {
    const edge = document.documentElement.clientWidth + 1;
    return Array.from(document.querySelectorAll("main section"))
      .filter((s) => s.getBoundingClientRect().right > edge)
      .map((s) => s.querySelector("h2")?.textContent || "(untitled panel)");
  });
}

/** A control on the top bar sits wholly inside the window. */
async function expectInWindow(page, what, control, width) {
  await expect(control, `${what} is on the bar`).toBeVisible();
  const box = await control.boundingBox();
  expect(box.x, `${what} starts left of the window`).toBeGreaterThanOrEqual(0);
  expect(box.x + box.width, `${what} runs past the right edge`).toBeLessThanOrEqual(width + 1);
}

/** The panel a menu button has open, found through aria-controls. */
async function panelOf(page, button) {
  await openMenu(button);
  return page.locator(`[id="${await button.getAttribute("aria-controls")}"]`);
}

test.describe("the dashboard at laptop width", () => {
  test("nothing runs past the window: the schedule, the atlas and every panel fit without a sideways scroll", async ({ page }) => {
    await open(page, "/", "Dashboard");
    const section = (name) => page.locator("section").filter({ has: page.getByRole("heading", { name, level: 2 }) });
    const schedule = section("Lead schedule");
    const atlas = section("Coverage atlas");
    // The atlas is requested beside the rest: wait until it has drawn.
    const squares = atlas.getByRole("group", { name: /controls grouped by framework/ }).getByRole("button");
    await expect(schedule.getByRole("table")).toBeVisible();
    await expect(squares.first()).toBeVisible();

    // The last column of the schedule, in the header and in the footed total,
    // and the last square drawn, sit inside their panels and the window, and
    // the schedule needs no scroller of its own at this width.
    await expectOnScreen(page, "the readiness column", schedule.getByRole("columnheader", { name: "Readiness" }));
    await expectOnScreen(page, "the total's readiness", schedule.locator("tfoot td").last());
    await expectOnScreen(page, "the last control in the atlas", squares.last());

    expect(await panelsPastTheEdge(page)).toEqual([]);
    expect(await pageOverflow(page)).toBeLessThanOrEqual(1);
  });
});

test.describe("the top bar at laptop width", () => {
  test("every control and every menu panel fits inside the window", async ({ page }) => {
    await open(page, "/", "Dashboard");
    const bell = page.getByRole("button", { name: /^Notifications/ });
    for (const [what, control] of [
      ["the Governance tab", governanceButton(page)],
      ["the search field", searchButton(page)],
      ["the Appearance button", appearanceButton(page)],
      ["the notification bell", bell],
      ["the account button", accountButton(page)],
    ]) {
      await expectInWindow(page, what, control, LAPTOP.width);
    }

    // Each panel opens whole: inside the window across and down.
    for (const [what, button] of [
      ["the Governance panel", governanceButton(page)],
      ["the Appearance panel", appearanceButton(page)],
      ["the notification tray", bell],
      ["the account menu", accountButton(page)],
    ]) {
      const panel = await panelOf(page, button);
      await expect(panel).toBeVisible();
      // Let the pop-in finish: the panel scales from 0.98 as it arrives.
      await expect.poll(async () => (await panel.boundingBox()).width).toBeGreaterThan(100);
      const box = await panel.boundingBox();
      expect(box.x, `${what} starts left of the window`).toBeGreaterThanOrEqual(0);
      expect(box.x + box.width, `${what} runs past the right edge`).toBeLessThanOrEqual(LAPTOP.width + 1);
      expect(box.y + box.height, `${what} runs past the bottom`).toBeLessThanOrEqual(LAPTOP.height + 1);
      await page.keyboard.press("Escape");
    }
    expect(await pageOverflow(page)).toBeLessThanOrEqual(1);
  });
});

// Between a phone and a laptop the search collapses to an icon and the
// wordmark and the version chip give way, so the bar is tightest here.
test.describe("at 1024 wide", () => {
  const NARROW = { width: 1024, height: 768 };
  test.use({ viewport: NARROW });
  const ROUTES = [
    ["/", "Dashboard"], ["/analytics", "Analytics"], ["/controls", "Controls"], ["/documents", "Documents"],
    ["/users", "Users"], ["/user-audit", "User audit"], ["/packages", "Audit packages"], ["/vendors", "Vendors"],
    ["/responsibilities", "Responsibility matrix"], ["/audit-log", "Audit log"], ["/meetings", "Meetings"],
    ["/groups", "Champion groups"], ["/risks", "Risk register"], ["/jira", "Jira boards"], ["/settings", "Settings"],
  ];

  test("the bar keeps its controls on screen and the search folds to an icon", async ({ page }) => {
    await open(page, "/", "Dashboard");
    for (const [what, control] of [
      ["the Governance tab", governanceButton(page)],
      ["the search button", searchButton(page)],
      ["the Appearance button", appearanceButton(page)],
      ["the notification bell", page.getByRole("button", { name: /^Notifications/ })],
      ["the account button", accountButton(page)],
    ]) {
      await expectInWindow(page, what, control, NARROW.width);
    }
    // An icon, not the field: its label is for screen readers only.
    expect((await searchButton(page).boundingBox()).width).toBeLessThan(60);
    // The Governance panel opens whole.
    const panel = await panelOf(page, governanceButton(page));
    await expect.poll(async () => (await panel.boundingBox()).width).toBeGreaterThan(100);
    const box = await panel.boundingBox();
    expect(box.x + box.width).toBeLessThanOrEqual(NARROW.width + 1);
  });

  for (const [path, heading] of ROUTES) {
    test(`${path} does not scroll the page sideways`, async ({ page }) => {
      await open(page, path, heading);
      expect(await pageOverflow(page)).toBeLessThanOrEqual(1);
    });
  }
});
