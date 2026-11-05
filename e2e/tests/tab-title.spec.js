import { test, expect, open, navLink } from "../fixtures.js";

// A white-label add-on swaps the product name in the tab for the brand's, after a page of ours has already put its
// name there. The page name must go on following the pages, whichever product name is in the tab.
async function go(page, path) {
  await (await navLink(page, path)).click();
}

test.describe("the browser tab title", () => {
  test("names the page and the product", async ({ page }) => {
    await open(page, "/", "Dashboard");
    await expect(page).toHaveTitle("Dashboard · Conformiti");
    await go(page, "/risks");
    await expect(page).toHaveTitle("Risk register · Conformiti");
    await go(page, "/");
    await expect(page).toHaveTitle("Dashboard · Conformiti");
  });

  test("keeps following the pages after an add-on put its own product name in the tab", async ({ page }) => {
    await open(page, "/", "Dashboard");
    await expect(page).toHaveTitle("Dashboard · Conformiti");
    await page.evaluate(() => { document.title = document.title.replace("Conformiti", "Acme GRC"); });
    await expect(page).toHaveTitle("Dashboard · Acme GRC");

    await go(page, "/risks");
    await expect(page).toHaveTitle("Risk register · Acme GRC");
    await go(page, "/");
    await expect(page).toHaveTitle("Dashboard · Acme GRC");
    await go(page, "/risks");
    await expect(page).toHaveTitle("Risk register · Acme GRC");
  });
});
