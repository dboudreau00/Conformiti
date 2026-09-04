import { test, expect } from "../fixtures.js";

test.describe("control register", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/controls");
    await expect(page.getByRole("heading", { name: "Controls" })).toBeVisible();
    await page.waitForLoadState("networkidle");
  });

  test("shows every seeded control, not just the first page", async ({ page }) => {
    // 217 controls across three frameworks arrive over five paginated pages.
    // Reading only the first was a real 0.2.0 defect on four screens.
    await expect(page.getByText(/SHOWING 217 OF 217/i)).toBeVisible();
    await expect(page.getByRole("tab", { name: /All frameworks/i })).toBeVisible();
  });

  test("the framework tabs narrow the register", async ({ page }) => {
    await page.getByRole("tab", { name: /ISO\/IEC 27001/ }).click();
    await expect(page.getByText(/SHOWING 93 OF 93/i)).toBeVisible();

    await page.getByRole("tab", { name: /PCI DSS/ }).click();
    await expect(page.getByText(/SHOWING 63 OF 63/i)).toBeVisible();

    await page.getByRole("tab", { name: /SOC 2/ }).click();
    await expect(page.getByText(/SHOWING 61 OF 61/i)).toBeVisible();

    await page.getByRole("tab", { name: /All frameworks/i }).click();
    await expect(page.getByText(/SHOWING 217 OF 217/i)).toBeVisible();
  });

  test("the status filter narrows the register", async ({ page }) => {
    await page.getByRole("button", { name: /^Implemented/ }).click();
    await expect(page.getByText(/SHOWING 62 OF 217/i)).toBeVisible();
    await page.getByRole("button", { name: /^Every status/ }).click();
    await expect(page.getByText(/SHOWING 217 OF 217/i)).toBeVisible();
  });

  test("search matches on reference and on title", async ({ page }) => {
    const search = page.getByRole("searchbox", { name: /search controls/i });
    await search.fill("A.5.1");
    await expect(page.getByText("Policies for information security")).toBeVisible();

    await search.fill("segregation of duties");
    await expect(page.getByText("Segregation of duties")).toBeVisible();
    await expect(page.getByText("Threat intelligence")).toHaveCount(0);

    await search.fill("zzz-no-such-control");
    await expect(page.getByText(/SHOWING 0 OF 217/i)).toBeVisible();
  });

  test("a control row expands to show its linked evidence", async ({ page }) => {
    const search = page.getByRole("searchbox", { name: /search controls/i });
    // A.5.1 is seeded with two evidence documents.
    await search.fill("A.5.1");
    await page.getByText("Policies for information security").click();
    await expect(page.getByText(/evidence/i).first()).toBeVisible();
  });

  test("every control carries a readiness score and band", async ({ page }) => {
    // The register's whole point in 0.3.0: a graded figure, not a tick box.
    await expect(page.getByText("Readiness", { exact: true })).toBeVisible();
    const search = page.getByRole("searchbox", { name: /search controls/i });
    await search.fill("A.5.1");
    await expect(page.getByText(/Ready|Nearly there|At risk|Not ready|Excluded/).first())
      .toBeVisible();
  });

  test("expanding a control explains its score", async ({ page }) => {
    const search = page.getByRole("searchbox", { name: /search controls/i });
    await search.fill("A.5.1");
    await page.getByText("Policies for information security").click();
    await page.waitForLoadState("networkidle");
    // Each of the five signals is named, with its own points and a reason.
    // Not exact-matched: the label and its explanation share a text node.
    const breakdown = page.getByRole("listitem").filter({ hasText: /\d+\/\d+$/ });
    await expect(breakdown).toHaveCount(5);
    // Every row explains itself rather than just showing a number.
    const text = (await breakdown.allInnerTexts()).join(" | ");
    for (const signal of ["Implementation", "Owner", "Evidence", "Freshness", "Testing"]) {
      expect(text, `${signal} row missing`).toContain(signal);
    }
    expect(text).toMatch(/Marked implemented|Not started|Implementation in progress/);
    expect(text).toMatch(/document\(s\) linked|No evidence linked/);
    // And it says what to do next, not just what is wrong.
    await expect(page.getByText(/^Next: /)).toBeVisible();
  });

  test("exporting the register downloads a CSV", async ({ page }) => {
    const download = page.waitForEvent("download");
    await page.getByRole("button", { name: /export csv/i }).click();
    const file = await download;
    expect(file.suggestedFilename()).toMatch(/\.csv$/);
  });
});
