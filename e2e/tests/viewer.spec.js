import { test, expect, open, signIn, DEMO } from "../fixtures.js";

async function openFolder(page, labels) {
  for (const label of labels) {
    await page.getByRole("treeitem", { name: label }).first().click();
  }
  await page.waitForLoadState("networkidle");
}

test.describe("in-browser document viewer", () => {
  test("a text document opens in the viewer with its frame of facts", async ({ page }) => {
    await open(page, "/documents", "Documents");
    await openFolder(page, [/SOC 2/i, /^CC6\b/i, /CC6\.1/i]);
    await page.getByRole("button", { name: "Access Control Policy", exact: true }).click();
    const dialog = page.getByRole("dialog", { name: /Viewing Access Control Policy/ });
    await expect(dialog).toBeVisible();
    await expect(dialog.getByText("Text", { exact: true })).toBeVisible();
    await expect(dialog.getByText(/demo file/)).toBeVisible();
    await expect(dialog.getByText("Satisfies controls", { exact: true })).toBeVisible();
    // The digest is computed from the bytes on screen, in the browser.
    await dialog.getByRole("button", { name: "Compute digest" }).click();
    await expect(dialog.getByText(/^[0-9a-f]{64}$/)).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(dialog).toBeHidden();
  });

  test("a PDF is drawn onto canvases by pdf.js; an image renders natively", async ({ page }) => {
    await open(page, "/documents", "Documents");
    await openFolder(page, [/ISO/i, /^A\.8\b/i, /A\.8\.8/i]);
    await page.getByRole("button", { name: "Penetration Test Report", exact: true }).click();
    const dialog = page.getByRole("dialog", { name: /Viewing Penetration Test Report/ });
    await expect(dialog).toBeVisible();
    await expect(dialog.getByText("PDF", { exact: true })).toBeVisible();
    // No frame, no plugin: pages are canvases drawn in our own page.
    await expect(dialog.locator("iframe")).toHaveCount(0);
    const canvas = dialog.locator("canvas[data-page='1']");
    await expect(canvas).toBeVisible();
    await expect(canvas).toHaveAttribute("data-zoom", "1");
    await expect(dialog.getByText(/1 page · 100%/)).toBeVisible();
    // Something was actually painted: a rendered page is not a blank canvas.
    const painted = await canvas.evaluate((c) => {
      const ctx = c.getContext("2d");
      const px = ctx.getImageData(0, 0, c.width, c.height).data;
      let dark = 0;
      for (let i = 0; i < px.length; i += 4) if (px[i] < 128 && px[i + 3] > 0) dark++;
      return dark;
    });
    expect(painted).toBeGreaterThan(50);
    await dialog.getByRole("button", { name: "Zoom in" }).click();
    await expect(dialog.getByText(/125%/)).toBeVisible();
    await expect(dialog.getByText(/^[0-9a-f]{64}$/)).toBeVisible();
    await dialog.getByRole("button", { name: "Close viewer" }).click();
    await expect(dialog).toBeHidden();

    await openFolder(page, [/^A\.7\b/i, /A\.7\.2/i]);
    await page.getByRole("button", { name: "Data Centre Badge Reader Photo", exact: true }).click();
    const image = page.getByRole("dialog", { name: /Viewing Data Centre Badge Reader Photo/ });
    await expect(image).toBeVisible();
    await expect(image.getByText("Image", { exact: true })).toBeVisible();
    await expect(image.locator("img")).toHaveAttribute("src", /^blob:/);
    await image.getByRole("button", { name: "Actual size" }).click();
    await expect(image.getByRole("button", { name: "Fit", exact: true })).toBeVisible();
    await image.getByRole("button", { name: "Close viewer" }).click();
    await expect(image).toBeHidden();
  });

  test("pinned package evidence opens for the auditor and matches the sealed digest", async ({ page }) => {
    await page.goto("/login");
    await page.evaluate(() => localStorage.clear());
    await signIn(page, DEMO.auditor);
    await open(page, "/packages", "Audit packages");
    await page.getByRole("button", { name: /Access Control Policy/ }).first().click();
    const dialog = page.getByRole("dialog", { name: /Viewing Access Control Policy/ });
    await expect(dialog).toBeVisible();
    await expect(dialog.getByText("Digest recorded at sealing", { exact: false })).toBeVisible();
    const sealed = (await dialog.locator("dd.font-mono").first().textContent()).trim();
    expect(sealed).toMatch(/^[0-9a-f]{64}$/);
    await dialog.getByRole("button", { name: "Compute digest" }).click();
    await expect(dialog.locator("p.font-mono", { hasText: sealed })).toBeVisible();
  });

  test("evidence linked to a control opens from the register", async ({ page }) => {
    await open(page, "/controls", "Controls");
    await page.getByLabel("Search controls", { exact: true }).fill("CC6.1");
    const row = page.getByRole("main").locator("[aria-expanded]").first();
    await expect(row).toContainText("CC6.1");
    await row.click();
    await page.getByRole("button", { name: "Access Control Policy", exact: true }).first().click();
    await expect(page.getByRole("dialog", { name: /Viewing Access Control Policy/ })).toBeVisible();
  });
});
