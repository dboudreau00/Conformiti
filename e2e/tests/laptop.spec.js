/**
 * The four screens that did not fit a 1366 by 768 laptop.
 *
 * The access review's decision and justification columns, the document table
 * and the vendor responsibility matrix all ran past the right edge, and the
 * columns a reviewer uses on every row were the ones off screen. This pins
 * the fix, because the release notes make the claim and nothing tested it.
 *
 * A table that scrolls inside its own panel is fine and deliberate. The page
 * itself scrolling is not: the sidebar and the header travel with it and
 * nothing stays where the eye left it.
 */
import { test, expect } from "../fixtures.js";

const LAPTOP = { width: 1366, height: 768 };

test.use({ viewport: LAPTOP });

async function pageOverflow(page) {
  return page.evaluate(() => {
    const d = document.documentElement;
    return d.scrollWidth - d.clientWidth;
  });
}

test.describe("laptop width", () => {
  for (const [name, path] of [
    ["the access review", "/user-audit"],
    ["the document table", "/documents"],
    ["the vendor matrix", "/vendors"],
    ["the responsibility matrix", "/responsibilities"],
  ]) {
    test(`${name} does not scroll the page sideways`, async ({ page }) => {
      await page.goto(path);
      await page.waitForLoadState("networkidle");
      await page.waitForTimeout(1200);
      // One pixel of slack: a scrollbar gutter is not a layout failure.
      expect(await pageOverflow(page)).toBeLessThanOrEqual(1);
    });
  }

  test("the reviewer's own controls are on screen", async ({ page }) => {
    await page.goto("/user-audit");
    await page.waitForLoadState("networkidle");
    await page.waitForTimeout(1200);

    // The decision control is the point of the screen. Off the right edge it
    // is unusable however gracefully the rest of the page scrolls.
    const decision = page.locator("main select, main [role='radiogroup']").first();
    if (await decision.count()) {
      const box = await decision.boundingBox();
      expect(box).not.toBeNull();
      expect(box.x + box.width).toBeLessThanOrEqual(LAPTOP.width);
    }
  });
});
