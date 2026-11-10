import { test, expect, expectBrowserError, open } from "../fixtures.js";

function tab(page, name) {
  return page.getByRole("tablist", { name: "Vendor sections" }).getByRole("tab", { name, exact: true });
}

test.describe("questionnaire sent to the vendor", () => {
  test("the vendor answers by link and the result comes back for review", async ({ page, browser }) => {
    await open(page, "/vendors", "Vendors");
    await page.getByRole("button", { name: /Brightline Security/ }).click();
    await tab(page, "Questionnaire").click();
    await expect(page.getByText("Nothing sent yet")).toBeVisible();

    // The header button and the empty state's own both open the form: take the header's.
    await page.getByRole("button", { name: "Send to the vendor" }).first().click();
    await page.locator("#qsend-email").fill("security@brightline.example");
    await page.locator("#qsend-message").fill("Please answer before the audit starts.");
    await page.getByRole("button", { name: "Send", exact: true }).click();
    const link = (await page.locator("#questionnaire-link").textContent()).trim();
    expect(link).toMatch(/\/questionnaire\/[A-Za-z0-9_-]{40,}$/);
    await expect(page.getByText("security@brightline.example").first()).toBeVisible();
    await expect(page.getByText("Open", { exact: true })).toBeVisible();

    // Revoking the link asks first, and cancelling leaves it open.
    await page.getByRole("button", { name: "Revoke the link sent to security@brightline.example" }).click();
    const revoke = page.getByRole("dialog", { name: "Revoke the link sent to security@brightline.example?" });
    await expect(revoke).toContainText("The vendor can no longer open it.");
    await revoke.getByRole("button", { name: "Cancel" }).click();
    await expect(revoke).toHaveCount(0);
    await expect(page.getByText("Open", { exact: true })).toBeVisible();

    // The vendor, in a browser of their own with no account.
    const vendorContext = await browser.newContext();
    const vendor = await vendorContext.newPage();
    try {
      await vendor.goto(link);
      await expect(vendor.getByRole("heading", { name: /Security questionnaire for Brightline Security/ })).toBeVisible();
      await expect(vendor.getByText("Please answer before the audit starts.")).toBeVisible();
      await expect(vendor.getByRole("navigation", { name: "Primary", exact: true })).toHaveCount(0);

      const items = vendor.getByRole("listitem");
      // The answer buttons are a group named for their question, so a screen reader hears which one they answer.
      const question = (await items.nth(0).locator("p").first().textContent()).trim();
      await expect(vendor.getByRole("group", { name: question, exact: true }).first().getByRole("button")).toHaveCount(4);
      await items.nth(0).getByRole("button", { name: "Yes", exact: true }).click();
      await items.nth(1).getByRole("button", { name: "No", exact: true }).click();
      await items.nth(1).getByLabel(/^Note for:/).fill("Planned for next quarter");
      await vendor.getByRole("button", { name: "Save draft" }).click();
      await expect(vendor.getByText(/Draft saved/)).toBeVisible();

      await vendor.reload();
      await expect(vendor.getByRole("listitem").nth(0).getByRole("button", { name: "Yes", exact: true }))
        .toHaveAttribute("aria-pressed", "true");
      await expect(vendor.getByText("2/12 answered")).toBeVisible();

      await vendor.locator("#q-name").fill("Nia Vendor");
      await vendor.locator("#q-title").fill("CISO");
      await vendor.getByRole("button", { name: "Submit questionnaire" }).click();
      const confirm = vendor.getByRole("dialog", { name: "Submit your answers?" });
      await expect(confirm).toBeVisible();
      await expect(confirm).toHaveAccessibleDescription(/^2 of 12 questions answered, 10 left blank\./);
      await confirm.getByRole("button", { name: "Submit answers", exact: true }).click();
      await expect(vendor.getByRole("heading", { name: "Thank you" })).toBeVisible();

      await vendor.reload();
      await expect(vendor.getByRole("heading", { name: /Already submitted/ })).toBeVisible();
    } finally {
      await vendorContext.close();
    }

    await page.reload();
    await page.getByRole("button", { name: /Brightline Security/ }).click();
    await tab(page, "Questionnaire").click();
    await expect(page.getByText(/Returned by Nia Vendor \(CISO\)/)).toBeVisible();
    await expect(page.getByLabel(/^Note for:/).nth(1)).toHaveValue("Planned for next quarter");
    await page.getByRole("button", { name: "Exceptions noted", exact: true }).click();
    await expect(page.getByText(/Outcome recorded/)).toBeVisible();
    await expect(page.getByText(/Returned by Nia Vendor/)).toHaveCount(0);
    await expect(page.getByText("Submitted", { exact: true })).toBeVisible();
  });
});

test.describe("a questionnaire link that cannot be loaded", () => {
  test("says so under the brand header, and Try again asks the server again", async ({ page }) => {
    expectBrowserError(page, /status of (500|404)/);
    let failing = true;
    await page.route("**/api/questionnaire/**", (route) => {
      if (!failing) return route.continue();
      return route.fulfill({ status: 500, contentType: "application/json", body: "{}" });
    });
    await page.goto("/questionnaire/not-a-real-link-token-0000000000000000");
    await expect(page.getByRole("heading", { name: "The questionnaire could not be loaded" })).toBeVisible();
    await expect(page.getByText("Security questionnaire", { exact: true })).toBeVisible();

    failing = false;
    await page.getByRole("button", { name: "Try again" }).click();
    await expect(page.getByRole("heading", { name: "This link is not valid" })).toBeVisible();
  });
});

test.describe("a questionnaire link that closes while the form is open", () => {
  test("saving a draft on a revoked link shows the closed screen, not a form that cannot be sent", async ({ page }) => {
    expectBrowserError(page, /status of 400/);
    await page.route("**/api/questionnaire/**", (route) => {
      if (route.request().method() === "GET") {
        return route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            status: "open",
            vendor: "Brightline Security Ltd",
            organisation: "Lumen Works",
            sender: "Mia Manager",
            message: "",
            expires_at: "2099-01-01T00:00:00Z",
            saved_at: null,
            answers: {},
            questions: [{ id: "q1", area: "Access", text: "Is two-factor required for staff?" }],
          }),
        });
      }
      return route.fulfill({
        status: 400,
        contentType: "application/json",
        body: JSON.stringify({ detail: "This link was withdrawn.", code: "revoked" }),
      });
    });
    await page.goto("/questionnaire/a-link-token-that-is-mocked-000000000000000000");
    await expect(page.getByRole("heading", { name: /Security questionnaire for Brightline Security/ })).toBeVisible();
    await page.getByRole("button", { name: "Yes", exact: true }).click();
    await page.getByRole("button", { name: "Save draft" }).click();
    await expect(page.getByRole("heading", { name: "This link was withdrawn" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Save draft" })).toHaveCount(0);
  });
});
