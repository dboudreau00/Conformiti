import { test, expect, open } from "../fixtures.js";

function tab(page, name) {
  return page.getByRole("tablist", { name: "Vendor sections" }).getByRole("tab", { name, exact: true });
}

test.describe("questionnaire sent to the vendor", () => {
  test("the vendor answers by link and the result comes back for review", async ({ page, browser }) => {
    await open(page, "/vendors", "Vendors");
    await page.getByRole("button", { name: /Brightline Security/ }).click();
    await tab(page, "Questionnaire").click();
    await expect(page.getByText("Nothing sent yet.")).toBeVisible();

    // Send the link.
    await page.getByRole("button", { name: "Send to the vendor" }).click();
    await page.locator("#qsend-email").fill("security@brightline.example");
    await page.locator("#qsend-message").fill("Please answer before the audit starts.");
    await page.getByRole("button", { name: "Send", exact: true }).click();
    const link = (await page.locator("#questionnaire-link").textContent()).trim();
    expect(link).toMatch(/\/questionnaire\/[A-Za-z0-9_-]{40,}$/);
    await expect(page.getByText("security@brightline.example").first()).toBeVisible();
    await expect(page.getByText("open", { exact: true })).toBeVisible();

    // The vendor, in a browser of their own with no account.
    const vendorContext = await browser.newContext();
    const vendor = await vendorContext.newPage();
    try {
      await vendor.goto(link);
      await expect(vendor.getByRole("heading", { name: /Security questionnaire for Brightline Security/ })).toBeVisible();
      await expect(vendor.getByText("Please answer before the audit starts.")).toBeVisible();
      await expect(vendor.getByRole("navigation", { name: "Primary", exact: true })).toHaveCount(0);

      const items = vendor.getByRole("listitem");
      await items.nth(0).getByRole("button", { name: "Yes", exact: true }).click();
      await items.nth(1).getByRole("button", { name: "No", exact: true }).click();
      await items.nth(1).getByLabel(/^Note for:/).fill("Planned for next quarter");
      await vendor.getByRole("button", { name: "Save draft" }).click();
      await expect(vendor.getByText(/Draft saved/)).toBeVisible();

      // The draft survives a reload of the link.
      await vendor.reload();
      await expect(vendor.getByRole("listitem").nth(0).getByRole("button", { name: "Yes", exact: true }))
        .toHaveAttribute("aria-pressed", "true");
      await expect(vendor.getByText("2/12 answered")).toBeVisible();

      await vendor.locator("#q-name").fill("Nia Vendor");
      await vendor.locator("#q-title").fill("CISO");
      await vendor.getByRole("button", { name: "Submit questionnaire" }).click();
      await expect(vendor.getByRole("heading", { name: "Thank you" })).toBeVisible();

      // Submits once: the link is now closed.
      await vendor.reload();
      await expect(vendor.getByRole("heading", { name: /Already submitted/ })).toBeVisible();
    } finally {
      await vendorContext.close();
    }

    // Back home: the answers wait for review, then the outcome is recorded.
    await page.reload();
    await page.getByRole("button", { name: /Brightline Security/ }).click();
    await tab(page, "Questionnaire").click();
    await expect(page.getByText(/Returned by Nia Vendor \(CISO\)/)).toBeVisible();
    await expect(page.getByLabel(/^Note for:/).nth(1)).toHaveValue("Planned for next quarter");
    await page.getByRole("button", { name: "Exceptions noted", exact: true }).click();
    await expect(page.getByText(/Outcome recorded/)).toBeVisible();
    await expect(page.getByText(/Returned by Nia Vendor/)).toHaveCount(0);
    await expect(page.getByText("submitted", { exact: true })).toBeVisible();
  });
});
