import { test, expect, expectBrowserError, open, signIn, DEMO } from "../fixtures.js";

// The seeded register: AWS (full matrix), Okta (report expiring), Stripe
// (report expired, linked risk) and Brightline (just onboarded, no matrix).
const tab = (page, name) => page.getByRole("tab", { name, exact: true });

test.describe("vendor register", () => {
  test("the register lists the seeded vendors with tier and risk rating", async ({ page }) => {
    await open(page, "/vendors", "Vendors");
    for (const name of [/Amazon Web Services/, /Okta/, /Stripe/, /Brightline Security/]) {
      await expect(page.getByRole("button", { name })).toBeVisible();
    }
    await expect(page.getByText("critical", { exact: true }).first()).toBeVisible();
    // Only the vendor with nothing stated wears the badge.
    await expect(page.getByText("no matrix", { exact: true })).toHaveCount(1);
  });

  test("a vendor's overview shows assurance posture, review clock and register entry", async ({ page }) => {
    await open(page, "/vendors", "Vendors");
    await page.getByRole("button", { name: /Amazon Web Services/ }).click();
    await expect(page.getByRole("heading", { name: "Amazon Web Services" })).toBeVisible();
    await expect(page.getByText("Risk rating", { exact: true })).toBeVisible();
    await expect(page.getByText(/\d+ current · \d+ expired/)).toBeVisible();
    await expect(page.getByText("Next review", { exact: true })).toBeVisible();
    await expect(page.getByText("Controls stated", { exact: true })).toBeVisible();
    await expect(page.getByRole("link", { name: "aws.amazon.com" })).toBeVisible();
  });

  // Runs before the walkthrough below: that test states Brightline's first
  // control, after which the "new vendor" alert rightly stops firing.
  test("the onboarding alert reaches the vendor's owner and deep-links to the matrix", async ({ page }) => {
    await page.goto("/login");
    await page.evaluate(() => localStorage.clear());
    await signIn(page, DEMO.manager);
    await open(page, "/", "Dashboard");
    await page.getByRole("button", { name: /Notifications/ }).click();
    const item = page.getByRole("button", { name: /New vendor: state responsibilities for Brightline/ }).first();
    await expect(item).toBeVisible();
    await item.click();
    await expect(page).toHaveURL(/\/vendors\?vendor=\d+&tab=matrix/);
    await expect(page.getByRole("heading", { name: "Brightline Security Ltd" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Shared responsibility matrix" })).toBeVisible();
  });

  test("the assurance tab lists what is on file and marks an expired report", async ({ page }) => {
    await open(page, "/vendors", "Vendors");
    await page.getByRole("button", { name: /Stripe/ }).click();
    await tab(page, "Assurance").click();
    await expect(page.getByText(/PCI DSS Attestation of Compliance/).first()).toBeVisible();
    await expect(page.getByText("expired", { exact: true }).first()).toBeVisible();
  });

  test("the shared responsibility matrix is an editable grid over the controls", async ({ page }) => {
    await open(page, "/vendors", "Vendors");
    await page.getByRole("button", { name: /Amazon Web Services/ }).click();
    await tab(page, "Responsibility matrix").click();
    await expect(page.getByText("Controls in scope", { exact: true })).toBeVisible();
    await expect(page.getByText("Stated", { exact: true })).toBeVisible();
    // A seeded statement is in the grid, editable by a frameworks manager.
    await page.getByRole("button", { name: "PCI DSS", exact: true }).click();
    await expect(page.getByLabel("What Amazon Web Services does for 1.3", { exact: true })).toHaveValue(/Edge network controls/);
    // Typing marks the row unsaved until Save is pressed.
    await page.getByLabel("What we do for 12.1", { exact: true }).fill("Our policy, our review cycle.");
    await expect(page.getByText("unsaved", { exact: true })).toBeVisible();
    await page.getByRole("button", { name: /Save 1 change/ }).click();
    await expect(page.getByText("1 control(s) saved.")).toBeVisible();
  });

  test("importing the vendor's own CSV recognises columns and values, then confirms", async ({ page }) => {
    await open(page, "/vendors", "Vendors");
    await page.getByRole("button", { name: /Amazon Web Services/ }).click();
    await tab(page, "Responsibility matrix").click();
    await page.getByRole("button", { name: /Import CSV\/XLSX/ }).click();
    await page.getByLabel("Framework in the file").selectOption("pci_dss_v4");
    await page.getByLabel("Matrix file").setInputFiles({
      name: "aws-matrix.csv",
      mimeType: "text/csv",
      // The AWS layout: a column per party, X marks under each -- and the
      // vendor is registered under its full name, not "AWS".
      buffer: Buffer.from("Requirement,AWS,Customer\n1.3,X,X\n12.1,,X\nZZ9,X,\n"),
    });
    // The header report says how each column was read...
    await expect(page.getByText(/AWS → provider mark/)).toBeVisible();
    await expect(page.getByText(/Customer → customer mark/)).toBeVisible();
    // ...and the honest tally: one reference the register does not have.
    await expect(page.getByText("2 matched a control")).toBeVisible();
    await expect(page.getByText("1 unmatched")).toBeVisible();
    // Nothing was written by parsing; confirming writes exactly the usable rows.
    await page.getByRole("button", { name: /Import 2 row/ }).click();
    await expect(page.getByText(/2 row\(s\) imported/)).toBeVisible();
    await expect(page.getByText("import", { exact: true }).first()).toBeVisible();
  });

  test("the matrix exports as CSV", async ({ page }) => {
    await open(page, "/vendors", "Vendors");
    await page.getByRole("button", { name: /Amazon Web Services/ }).click();
    await tab(page, "Responsibility matrix").click();
    const download = page.waitForEvent("download");
    await page.getByRole("button", { name: "Export", exact: true }).click();
    expect((await download).suggestedFilename()).toMatch(/^responsibility-matrix-.*\.csv$/);
  });

  test("a newly onboarded vendor is prompted through its controls", async ({ page }) => {
    await open(page, "/vendors", "Vendors");
    await page.getByRole("button", { name: /Brightline Security/ }).click();
    await expect(page.getByText(/no responsibilities stated yet/)).toBeVisible();
    await page.getByRole("button", { name: "Walk me through it" }).click();
    const prompt = page.getByRole("region", { name: "Responsibility prompt" });
    await expect(prompt.getByText(/Control 1 of \d+ without a statement/)).toBeVisible();
    const first = await prompt.locator("h3").textContent();
    await prompt.getByRole("button", { name: "Provider", exact: true }).click();
    await prompt.getByLabel(/What Brightline Security Ltd does/).fill("Runs the annual external test.");
    await prompt.getByRole("button", { name: "Save and next" }).click();
    // The saved control leaves the queue; the prompt moves on without skipping one.
    await expect(prompt.getByText(/Control 1 of \d+ without a statement/)).toBeVisible();
    await expect(prompt.locator("h3")).not.toHaveText(first);
    await expect(page.getByText(/no responsibilities stated yet/)).toHaveCount(0);
  });

  test("a viewer can read the register but not change it", async ({ page }) => {
    await page.goto("/login");
    await page.evaluate(() => localStorage.clear());
    await signIn(page, DEMO.viewer);
    await open(page, "/vendors", "Vendors");
    await page.getByRole("button", { name: /Amazon Web Services/ }).click();
    await expect(page.getByRole("heading", { name: "Amazon Web Services" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Register a vendor" })).toHaveCount(0);
    await tab(page, "Responsibility matrix").click();
    await expect(page.getByText("Controls in scope", { exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: /Import CSV/ })).toHaveCount(0);
  });
});

test.describe("responsibility matrix (RACI)", () => {
  test("every control has a row and the gaps are counted", async ({ page }) => {
    await open(page, "/responsibilities", "Responsibility matrix");
    await expect(page.getByText("No Accountable", { exact: true })).toBeVisible();
    await expect(page.getByText("No Responsible", { exact: true })).toBeVisible();
    await expect(page.getByText("Shared with a vendor", { exact: true })).toBeVisible();
    await page.getByRole("button", { name: "SOC 2", exact: true }).click();
    await page.getByLabel("Search controls", { exact: true }).fill("CC6.1");
    // Explicit rows from the seed, and the implied vendor from Okta's matrix.
    await expect(page.getByText("Mia Manager", { exact: true }).first()).toBeVisible();
    await expect(page.getByText("Okta", { exact: true }).first()).toBeVisible();
    await expect(page.getByText("shared with vendor", { exact: true }).first()).toBeVisible();
  });

  test("a second Accountable party is refused", async ({ page }) => {
    expectBrowserError(page, /status of 400/);   // the refusal is the point
    await open(page, "/responsibilities", "Responsibility matrix");
    const control = page.getByLabel("Control", { exact: true });
    const value = await control.locator("option", { hasText: /CC6\.1 — / }).first().getAttribute("value");
    await control.selectOption(value);
    await page.getByLabel("Person", { exact: true }).selectOption({ label: "Owen Owner" });
    await page.getByLabel("Role", { exact: true }).selectOption("accountable");
    await page.getByRole("button", { name: "Assign", exact: true }).click();
    await expect(page.getByRole("alert")).toContainText(/already has an Accountable party/);
  });

  test("the matrix exports as CSV", async ({ page }) => {
    await open(page, "/responsibilities", "Responsibility matrix");
    const download = page.waitForEvent("download");
    await page.getByRole("button", { name: "Export", exact: true }).click();
    expect((await download).suggestedFilename()).toBe("responsibility-matrix.csv");
  });
});
