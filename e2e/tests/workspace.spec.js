import { test, expect, open } from "../fixtures.js";

/** Dashboard panels are unnamed <section> elements, so they carry no landmark
 *  role — anchor on the <h2> each one contains instead. */
function panel(page, heading) {
  return page.locator("section").filter({
    has: page.getByRole("heading", { name: heading, level: 2 }),
  });
}

test.describe("dashboard", () => {
  test.beforeEach(async ({ page }) => {
    await open(page, "/", "Dashboard");
  });

  test("the readiness card reports a figure and a trend", async ({ page }) => {
    await expect(page.getByText("Overall readiness")).toBeVisible();
    await expect(page.getByText(/of \d+ applicable controls implemented/)).toBeVisible();
    await expect(page.getByRole("img", { name: /readiness trend/i })).toBeVisible();
  });

  test("the calendar opens a day with an item on it", async ({ page }) => {
    const calendar = panel(page, "Compliance calendar");
    await expect(calendar).toBeVisible();
    const day = calendar.getByRole("button", { name: /, 1 item$/ }).first();
    await expect(day).toBeVisible();
    await day.click();
    await expect(page.getByText(/Review due:|access review/i).first()).toBeVisible();
  });

  test("the calendar type filters toggle without breaking the grid", async ({ page }) => {
    const calendar = panel(page, "Compliance calendar");
    const filters = calendar.getByRole("group", { name: /filter calendar by item type/i });
    for (const type of ["Review", "Audit", "Task", "Other"]) {
      await filters.getByRole("button", { name: type, exact: true }).click();
    }
    // Everything deselected: the month grid still renders, with no items.
    await expect(calendar.getByRole("button", { name: /, 0 items$/ }).first()).toBeVisible();
  });

  test("the review queue marks a document reviewed", async ({ page }) => {
    const queue = panel(page, "Reviews coming up");
    await expect(queue).toBeVisible();
    const button = queue.getByRole("button", { name: /^Mark .* reviewed$/ }).first();
    const label = await button.getAttribute("aria-label");
    await button.click();
    await page.waitForLoadState("networkidle");
    // The item leaves the queue once its next review date moves forward.
    await expect(queue.getByRole("button", { name: label, exact: true })).toHaveCount(0);
  });

  test("the evidence coverage meter is populated", async ({ page }) => {
    await expect(page.getByRole("progressbar", { name: /evidence coverage/i })).toBeVisible();
    await expect(page.getByText(/control–document links/)).toBeVisible();
  });
});

test.describe("documents", () => {
  test("the folder tree lists all three seeded frameworks", async ({ page }) => {
    await open(page, "/documents", "Documents");
    for (const framework of ["ISO-IEC 27001 2022", "PCI DSS 4.0.1", "SOC 2 2017 TSC (rev. 2022)"]) {
      await expect(page.getByText(framework, { exact: true }).first()).toBeVisible();
    }
    await expect(page.getByText("Pick a folder on the left")).toBeVisible();
  });

  test("selecting a folder shows its documents", async ({ page }) => {
    await open(page, "/documents", "Documents");
    await page.getByText("CC6 - Logical and Physical Access Controls", { exact: true }).first().click();
    await page.waitForLoadState("networkidle");
    await expect(page.getByText("Pick a folder on the left")).toHaveCount(0);
  });
});

test.describe("risk register", () => {
  test.beforeEach(async ({ page }) => {
    await open(page, "/risks", "Risk register");
  });

  test("live risks are listed with their rating band", async ({ page }) => {
    await expect(page.getByText("MFA not enforced for contractor accounts")).toBeVisible();
    await expect(page.getByText(/critical\s*·\s*16/i).first()).toBeVisible();
    await expect(page.getByText(/3 SHOWN · 4 TOTAL/i)).toBeVisible();
  });

  test("the heatmap plots only live risks", async ({ page }) => {
    await expect(page.getByText("Likelihood × impact")).toBeVisible();
    await expect(page.getByText(/Closed and accepted risks are not plotted/i)).toBeVisible();
  });

  test("opening a risk shows its detail", async ({ page }) => {
    await page.getByText("MFA not enforced for contractor accounts").click();
    await expect(page.getByText("SEC-341").first()).toBeVisible();
  });

  test("exporting the register downloads a file", async ({ page }) => {
    const download = page.waitForEvent("download");
    await page.getByRole("button", { name: "Export", exact: true }).click();
    expect((await download).suggestedFilename()).toMatch(/\.(csv|xlsx)$/);
  });
});
