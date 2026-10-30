import {
  test, expect, open, openMenu, governanceButton, accountButton, appearanceButton, searchButton,
} from "../fixtures.js";

const LAPTOP = { width: 1366, height: 768 };

test.use({ viewport: LAPTOP });

async function pageOverflow(page) {
  return page.evaluate(() => {
    const d = document.documentElement;
    return d.scrollWidth - d.clientWidth;
  });
}

/** Right edges of a row's control, its table, the panel holding both and the window. The table's reach is its
 *  nearest sideways scroller's scrollWidth: no bounding box shows columns that scroll out of sight. */
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

async function expectOnScreen(page, what, control) {
  await expect(control).toBeVisible();
  const r = await reach(control);
  // One pixel of slack: layout rounds to whole pixels.
  expect(r.table, `the table holding ${what} runs past its panel`).toBeLessThanOrEqual(r.panel + 1);
  expect(r.control, `${what} sits past the edge of its panel`).toBeLessThanOrEqual(r.panel + 1);
  expect(r.table, `the table holding ${what} runs past the window`).toBeLessThanOrEqual(r.viewport + 1);
  expect(r.control, `${what} sits past the edge of the window`).toBeLessThanOrEqual(r.viewport + 1);
  expect(await pageOverflow(page)).toBeLessThanOrEqual(1);
}

test.describe("laptop width", () => {
  test("the access review keeps the decision and the justification on screen", async ({ page }) => {
    await open(page, "/user-audit", "User audit");
    // The first row's own controls: the review picker above the grid sits at the left whatever the grid does.
    await expectOnScreen(page, "the decision",
      page.getByRole("radiogroup", { name: /^Decision for / }).first());
    await expectOnScreen(page, "the justification",
      page.getByRole("textbox", { name: /^Notes for / }).first());
  });

  test("the document table keeps its row actions on screen", async ({ page }) => {
    await open(page, "/documents", "Documents");
    for (const label of [/SOC 2/i, /^CC6\b/i, /CC6\.1/i]) {
      await page.getByRole("treeitem", { name: label }).first().click();
    }
    await expectOnScreen(page, "the row actions",
      page.getByRole("button", { name: /^Actions for / }).first());
  });

  test("the vendor responsibility matrix keeps its statements on screen", async ({ page }) => {
    await open(page, "/vendors", "Vendors");
    await page.getByRole("button", { name: /Amazon Web Services/ }).click();
    await expect(page.getByRole("heading", { name: "Amazon Web Services" })).toBeVisible();
    await page.getByRole("main").getByRole("tab", { name: "Responsibility matrix", exact: true }).click();
    await expect(page.getByRole("heading", { name: "Shared responsibility matrix" })).toBeVisible();
    await expectOnScreen(page, "the responsibility",
      page.getByRole("group", { name: /^Responsibility for / }).first());
    await expectOnScreen(page, "the statement",
      page.getByRole("textbox", { name: /^We do for / }).first());
  });

  // Its matrix is wider than its column here and scrolls inside its panel; the page itself must not scroll sideways.
  test("the RACI matrix does not scroll the page sideways", async ({ page }) => {
    await open(page, "/responsibilities", "Responsibility matrix");
    await expect(page.getByRole("main").getByRole("table").first()).toBeVisible();
    expect(await pageOverflow(page)).toBeLessThanOrEqual(1);
  });
});

function panelsPastTheEdge(page) {
  return page.evaluate(() => {
    const edge = document.documentElement.clientWidth + 1;
    return Array.from(document.querySelectorAll("main section"))
      .filter((s) => s.getBoundingClientRect().right > edge)
      .map((s) => s.querySelector("h2")?.textContent || "(untitled panel)");
  });
}

async function expectInWindow(page, what, control, width) {
  await expect(control, `${what} is on the bar`).toBeVisible();
  const box = await control.boundingBox();
  expect(box.x, `${what} starts left of the window`).toBeGreaterThanOrEqual(0);
  expect(box.x + box.width, `${what} runs past the right edge`).toBeLessThanOrEqual(width + 1);
}

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

// 1024 is where the bar is tightest: the search folds to an icon and the wordmark and version chip give way.
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
    expect((await searchButton(page).boundingBox()).width).toBeLessThan(60);
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
