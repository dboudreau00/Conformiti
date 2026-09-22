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
    // 0.9.5: once any control is applicable the headline is the register's
    // score out of 100, with the implemented share quoted beside it; an
    // empty programme still shows the share on its own.
    const label = page.getByText(/^(Readiness score|Overall readiness)$/);
    await expect(label).toBeVisible();
    if ((await label.textContent()).trim() === "Readiness score") {
      await expect(page.getByText("/100")).toBeVisible();
      // 0.9.5d: the card states the share, and the "i" beside the label
      // explains how the score is worked out, on hover or on focus.
      await expect(page.getByText(/\d+% of [\d,]+ applicable controls are marked implemented/)).toBeVisible();
      const why = page.getByRole("button", { name: /how the readiness score is worked out/i });
      await expect(why).toBeVisible();
      await why.hover();
      await expect(page.getByRole("tooltip")).toContainText(/mean score across [\d,]+ applicable controls/i);
    } else {
      await expect(page.getByText(/of \d+ applicable controls implemented/)).toBeVisible();
    }
    await expect(page.getByRole("img", { name: /readiness trend/i })).toBeVisible();
  });

  test("the calendar opens a day and its review entry opens the document", async ({ page }) => {
    const calendar = panel(page, "Compliance calendar");
    await expect(calendar).toBeVisible();
    // A day holding one review. Every seeded document falls due on a day of
    // its own, and at least one of them lands on this month's grid.
    const day = calendar.getByRole("button", { name: /, 1 item$/ }).filter({ hasText: "Review due:" }).first();
    await expect(day).toBeVisible();
    const date = (await day.getAttribute("aria-label")).replace(/, 1 item$/, "");
    const title = await day.locator("[title]").getAttribute("title");
    const doc = title.replace(/^Review due: /, "");
    await day.click();
    await expect(day).toHaveAttribute("aria-pressed", "true");

    // The grid chip was on screen before the click, so only the day detail
    // proves anything: its heading, its one entry and the entry's actions.
    await expect(calendar.getByRole("heading", { level: 3, name: date })).toBeVisible();
    const entry = calendar.getByRole("listitem");
    await expect(entry).toHaveCount(1);
    await expect(entry.getByRole("button", { name: `Mark ${doc} reviewed`, exact: true })).toBeVisible();

    // A review entry names a document, and opens it.
    const preview = page.waitForResponse((r) => r.url().includes("/preview/"));
    await entry.getByRole("button", { name: title, exact: true }).click();
    const viewer = page.getByRole("dialog", { name: `Viewing ${doc}` });
    await expect(viewer).toBeVisible();
    expect((await preview).status()).toBe(200);
    await page.keyboard.press("Escape");
    await expect(viewer).toBeHidden();
  });

  test("each calendar type filter narrows the grid to its own kind", async ({ page }) => {
    const calendar = panel(page, "Compliance calendar");
    const filters = calendar.getByRole("group", { name: /filter calendar by item type/i });
    const chips = filters.getByRole("button");
    // The entries on the month grid, each titled with its item's own title.
    const entries = calendar.getByRole("button", { name: /, \d+ items?$/ }).locator("[title]");
    const reviews = entries.filter({ hasText: /^Review due: / });
    const monthCount = async () => Number(
      (await calendar.getByText(/^\d+ items? this month$/).textContent()).match(/^\d+/)[0]);

    // Only a kind on this month's grid gets a chip. The seed puts both of its
    // audits 60 and 120 days out, past any month grid, so Audit gets none.
    await expect(chips.first()).toBeVisible();
    await expect(filters.getByRole("button", { name: "Audit" })).toHaveCount(0);
    const total = await monthCount();
    const count = await chips.count();

    let sum = 0;
    for (let i = 0; i < count; i += 1) {
      const chip = chips.nth(i);
      const review = /review/i.test(await chip.textContent());
      await chip.click();
      await expect(chip).toHaveAttribute("aria-pressed", "true");
      // Filtered, the grid still has entries, and only ones of that kind.
      await expect(entries.first()).toBeVisible();
      await expect(reviews).toHaveCount(review ? await entries.count() : 0);
      sum += await monthCount();
      // The chips are single-select: pressing this one again clears it.
      await chip.click();
      await expect(chip).toHaveAttribute("aria-pressed", "false");
    }
    // Each item is of exactly one kind, so the kinds add up to the month.
    expect(sum).toBe(total);
    expect(await monthCount()).toBe(total);
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
    // The seed links documents to controls, so a count of zero means the
    // summary lost its figures, not that there is nothing to count.
    await expect(page.getByText(/^[1-9]\d*\/\d+ controls$/)).toBeVisible();
    await expect(page.getByText(/^[1-9]\d* links between controls and documents\.$/)).toBeVisible();
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
