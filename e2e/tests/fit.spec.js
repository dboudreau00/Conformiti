import { test, expect, GOVERNANCE_ROUTES } from "../fixtures.js";

/**
 * The layout defect the other specs cannot see. The page does not scroll
 * sideways and nothing overlaps; a button just shows half a word because its
 * label wrapped inside a box one line high, or sits half under the edge of the
 * card that clips it. Each test opens every page at one width and asks every
 * control two questions: does its label fit it, and is it whole inside the
 * parent that would clip it. A control inside a table or other region that
 * scrolls sideways is exempt from the second, because there the person scrolls.
 */
const PAGES = ["/", "/analytics", "/controls", "/documents", ...GOVERNANCE_ROUTES, "/settings"];
const WIDTHS = [390, 1024, 1440];

function misfits() {
  const found = [];
  const viewport = document.documentElement.clientWidth;
  const controls = document.querySelectorAll(
    "button, a[href], [role=button], [role=tab], [role=menuitem], input:not([type=hidden]), select, textarea"
  );
  const isField = (el) => ["INPUT", "SELECT", "TEXTAREA"].includes(el.tagName);
  for (const el of controls) {
    if (el.closest(".sr-only")) continue;
    const box = el.getBoundingClientRect();
    if (!box.width || !box.height) continue;
    const name = (el.innerText || el.getAttribute("aria-label") || el.getAttribute("placeholder") || el.tagName)
      .trim().replace(/\s+/g, " ").slice(0, 40);

    if (!isField(el) && el.clientHeight && el.scrollHeight > el.clientHeight + 2) {
      found.push(`"${name}" wraps inside a box one line high`);
    }

    let scrolls = false;
    for (let p = el.parentElement; p; p = p.parentElement) {
      if (/(auto|scroll)/.test(getComputedStyle(p).overflowX)) { scrolls = true; break; }
    }
    if (scrolls) continue;
    if (box.right > viewport + 1) {
      found.push(`"${name}" runs ${Math.round(box.right - viewport)}px past the right edge of the screen`);
      continue;
    }
    for (let p = el.parentElement; p; p = p.parentElement) {
      if (!/(hidden|clip)/.test(getComputedStyle(p).overflowX)) continue;
      const edge = p.getBoundingClientRect();
      if (box.right > edge.right + 1 || box.left < edge.left - 1) {
        found.push(`"${name}" is cut off by the edge of its card`);
        break;
      }
    }
  }
  return found;
}

test.describe("every control fits", () => {
  for (const width of WIDTHS) {
    test(`at ${width}px wide no label is cut off and no control is clipped`, async ({ page }) => {
      test.setTimeout(240_000);
      await page.setViewportSize({ width, height: 900 });
      const problems = [];
      for (const path of PAGES) {
        await page.goto(path);
        await page.waitForLoadState("networkidle");
        await expect(page.getByRole("main").getByRole("heading", { level: 1 })).toBeVisible();
        // The shell is drawn at once and the page's own data after it.
        await page.waitForTimeout(400);
        for (const text of await page.evaluate(misfits)) problems.push(`${path}: ${text}`);
      }
      expect(problems).toEqual([]);
    });
  }
});
