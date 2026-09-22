/**
 * The three screens that did not fit a 1366 by 768 laptop.
 *
 * The access review's decision and justification columns, the document table
 * and the vendor responsibility matrix all ran past the right edge, and the
 * columns a reviewer uses on every row were the ones off screen. This pins
 * the fix, because the release notes make the claim and nothing tested it.
 *
 * Each of those tables already sat in a sideways scroller of its own, so the
 * page never scrolled even while the columns were off screen: they slid out
 * of sight inside the panel instead. The page staying still proves nothing on
 * its own. Each test therefore opens its screen until the table itself is
 * rendered, then measures how far the table reaches and where a control used
 * on every row sits, against the panel holding them and the window's width.
 */
import { test, expect, open } from "../fixtures.js";

const LAPTOP = { width: 1366, height: 768 };

test.use({ viewport: LAPTOP });

/** How far the page itself scrolls sideways. When it does, the sidebar and
 *  the header travel with it and nothing stays where the eye left it. */
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
