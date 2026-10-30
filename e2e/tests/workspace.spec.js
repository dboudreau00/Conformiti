import { test, expect, open, topHeading } from "../fixtures.js";

/** Dashboard panels are unnamed <section>s with no landmark role: anchor on the <h2> each one contains instead. */
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
    const label = page.getByText(/^(Readiness score|Overall readiness)$/);
    await expect(label).toBeVisible();
    if ((await label.textContent()).trim() === "Readiness score") {
      await expect(page.getByText("/100")).toBeVisible();
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
    // Every seeded document falls due on a day of its own, and at least one lands on this month's grid.
    const day = calendar.getByRole("button", { name: /, 1 item$/ }).filter({ hasText: "Review due:" }).first();
    await expect(day).toBeVisible();
    // The cell's name is its text, then the date and count for a screen reader; the date is in that last, hidden part.
    const date = (await day.locator("span.sr-only").last().textContent()).replace(/^,\s*/, "").replace(/, 1 item$/, "").trim();
    const title = await day.locator("[title]").getAttribute("title");
    const doc = title.replace(/^Review due: /, "");
    await day.click();
    await expect(day).toHaveAttribute("aria-pressed", "true");

    await expect(calendar.getByRole("heading", { level: 3, name: date })).toBeVisible();
    const entry = calendar.getByRole("listitem");
    await expect(entry).toHaveCount(1);
    await expect(entry.getByRole("button", { name: `Mark reviewed: ${doc}`, exact: true })).toBeVisible();

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
    const entries = calendar.getByRole("button", { name: /, \d+ items?$/ }).locator("[title]");
    const reviews = entries.filter({ hasText: /^Review due: / });
    const monthCount = async () => Number(
      (await calendar.getByText(/^\d+ items? this month$/).textContent()).match(/^\d+/)[0]);

    // Only a kind on this month's grid gets a chip: the seed's audits are 60 and 120 days out, so Audit gets none.
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
      await expect(entries.first()).toBeVisible();
      await expect(reviews).toHaveCount(review ? await entries.count() : 0);
      sum += await monthCount();
      await chip.click();
      await expect(chip).toHaveAttribute("aria-pressed", "false");
    }
    expect(sum).toBe(total);
    expect(await monthCount()).toBe(total);
  });

  test("the review queue marks a document reviewed", async ({ page }) => {
    const queue = panel(page, "Reviews coming up");
    await expect(queue).toBeVisible();
    const button = queue.getByRole("button", { name: /^Mark reviewed: / }).first();
    const label = await button.getAttribute("aria-label");
    await button.click();
    await page.waitForLoadState("networkidle");
    await expect(queue.getByRole("button", { name: label, exact: true })).toHaveCount(0);
  });

  test("the evidence coverage meter is populated", async ({ page }) => {
    await expect(page.getByRole("progressbar", { name: /evidence coverage/i })).toBeVisible();
    // The seed links documents to controls, so a count of zero means the summary lost its figures.
    await expect(page.getByText(/^[1-9]\d*\/\d+ controls$/)).toBeVisible();
    await expect(page.getByText(/^[1-9]\d* links between controls and documents\.$/)).toBeVisible();
  });

  const FRAMEWORKS = ["ISO/IEC 27001", "PCI DSS", "SOC 2"];
  const figure = (text) => Number(String(text).replace(/[^\d]/g, ""));
  /** The six figures of a row: Applicable, Implemented, In progress, Not started, Evidence linked, Readiness. */
  async function figures(row) {
    return (await row.locator("td").allTextContents()).map(figure);
  }

  /** "93 controls" from a row's sub line. Not from the whole row header: the
   *  framework's version runs straight into it ("4.0.1" then "63"). */
  async function controlsIn(row) {
    const sub = await row.getByRole("rowheader").getByText(/^[\d,]+ controls/).first().textContent();
    return figure(sub.match(/^[\d,]+/)[0]);
  }

  test("the lead schedule has one row per framework and a total that foots", async ({ page }) => {
    const schedule = panel(page, "Lead schedule");
    await expect(schedule).toBeVisible();
    await expect(schedule.getByText(`${FRAMEWORKS.length} frameworks`, { exact: true })).toBeVisible();
    const table = schedule.getByRole("table");
    await expect(table.getByRole("columnheader")).toHaveText([
      "Framework", "Applicable", "Implemented", "In progress", "Not started", "Evidence linked", "Readiness",
    ]);

    const rows = table.locator("tbody tr");
    await expect(rows).toHaveCount(FRAMEWORKS.length);
    for (const [i, name] of FRAMEWORKS.entries()) {
      await expect(rows.nth(i).getByRole("rowheader")).toContainText(name);
    }
    const total = table.locator("tfoot tr");
    await expect(total).toHaveCount(1);
    await expect(total.getByRole("rowheader")).toContainText("Total");

    const each = [];
    for (let i = 0; i < FRAMEWORKS.length; i += 1) each.push(await figures(rows.nth(i)));
    const foot = await figures(total);

    for (const row of [...each, foot]) {
      expect(row[0], "applicable = implemented + in progress + not started").toBe(row[1] + row[2] + row[3]);
    }
    for (let col = 0; col < 5; col += 1) {
      expect(each.reduce((sum, row) => sum + row[col], 0), `column ${col} foots`).toBe(foot[col]);
    }
    // Readiness is a score out of 100, not a count: the total quotes the programme's own figure, the headline.
    for (const row of each) expect(row[5]).toBeLessThanOrEqual(100);
    const headline = figure((await page.getByText("/100").locator("..").textContent()).replace("/100", ""));
    expect(foot[5]).toBe(headline);
    const withEvidence = figure((await page.getByText(/^[1-9]\d*\/\d+ controls$/).textContent()).split("/")[0]);
    expect(foot[4]).toBe(withEvidence);
  });

  test("a framework row opens the register filtered to that framework", async ({ page }) => {
    const row = panel(page, "Lead schedule").getByRole("table").locator("tbody tr").filter({ hasText: "SOC 2" });
    const controls = await controlsIn(row);
    await row.getByRole("link").click();
    await expect(page).toHaveURL(/\/controls\?framework=soc2$/);
    await expect(topHeading(page, "Controls")).toBeVisible();
    await expect(page.getByRole("tab", { name: /^SOC 2/ })).toHaveAttribute("aria-selected", "true");
    await expect(page.getByText(`Showing ${controls} of ${controls}`)).toBeVisible();
  });

  const atlas = (page) => panel(page, "Coverage atlas");
  const field = (page) => page.getByRole("group", { name: /controls grouped by framework/ });
  const squares = (page) => field(page).getByRole("button");
  const lit = (page) => field(page).locator('[data-lit="true"]');
  const card = (page) => page.getByRole("group", { name: "Selected control" });
  const refOf = async (square) => (await square.getAttribute("aria-label")).split(",")[0];

  test("every control is one square, grouped into a territory per framework in the schedule's order", async ({ page }) => {
    await expect(atlas(page)).toBeVisible();
    const total = figure((await page.getByText(/^[1-9]\d*\/\d+ controls$/).textContent()).split("/")[1]);
    await expect(field(page)).toHaveAccessibleName(`${total} controls grouped by framework`);
    await expect(squares(page)).toHaveCount(total);

    const territories = field(page).getByRole("group");
    await expect(territories).toHaveCount(FRAMEWORKS.length);
    const rows = panel(page, "Lead schedule").getByRole("table").locator("tbody tr");
    for (const [i, name] of FRAMEWORKS.entries()) {
      await expect(territories.nth(i)).toHaveAccessibleName(new RegExp(`^${name.replace("/", "\\/")}`));
      await expect(territories.nth(i).getByRole("button")).toHaveCount(await controlsIn(rows.nth(i)));
    }

    const foot = await figures(panel(page, "Lead schedule").getByRole("table").locator("tfoot tr"));
    const legend = atlas(page).getByRole("list", { name: "Legend with counts" });
    const notApplicable = total - foot[0];
    for (const [label, count] of [
      ["Implemented", foot[1]], ["In progress", foot[2]], ["Not started", foot[3]], ["Not applicable", notApplicable],
    ]) {
      await expect(legend.getByRole("listitem").filter({ hasText: label })).toContainText(String(count));
      await expect(field(page).getByRole("button", { name: new RegExp(`, ${label}$`) })).toHaveCount(count);
    }
  });

  test("the field is one tab stop, and the arrow keys move through the squares", async ({ page }) => {
    const all = squares(page);
    const stop = field(page).locator('button[tabindex="0"]');
    await expect(stop).toHaveCount(1);

    await all.first().focus();
    await page.keyboard.press("ArrowRight");
    await expect(all.nth(1)).toBeFocused();
    await expect(stop).toHaveCount(1);
    await expect(all.nth(1)).toHaveAttribute("tabindex", "0");
    await expect(all.first()).toHaveAttribute("tabindex", "-1");
    await page.keyboard.press("ArrowLeft");
    await expect(all.first()).toBeFocused();

    // Page coordinates, so a scroll between the two does not matter.
    const place = () => page.evaluate(() => {
      const r = document.activeElement.getBoundingClientRect();
      return { x: r.x + window.scrollX, y: r.y + window.scrollY };
    });
    const before = await place();
    await page.keyboard.press("ArrowDown");
    const after = await place();
    expect(after.x).toBeCloseTo(before.x, 0);
    expect(after.y).toBeGreaterThan(before.y);
    await page.keyboard.press("ArrowUp");
    await expect(all.first()).toBeFocused();

    const territories = field(page).getByRole("group");
    await page.keyboard.press("End");
    await expect(territories.first().getByRole("button").last()).toBeFocused();
    await page.keyboard.press("Home");
    await expect(all.first()).toBeFocused();
    await page.keyboard.press("PageDown");
    await expect(territories.nth(1).getByRole("button").first()).toBeFocused();

    const where = await page.evaluate(() => document.activeElement.getAttribute("aria-label"));
    await page.keyboard.press("Tab");
    await expect(field(page).locator(":focus")).toHaveCount(0);
    await page.keyboard.press("Shift+Tab");
    expect(await page.evaluate(() => document.activeElement.getAttribute("aria-label"))).toBe(where);
  });

  test("hovering or focusing a square lights the controls that answer the same theme and dims the rest", async ({ page }) => {
    const all = squares(page);
    await expect(lit(page)).toHaveCount(0);
    await expect(field(page)).toHaveAttribute("data-light", "false");

    await all.first().hover();
    await expect(lit(page).first()).toBeVisible();
    expect(await lit(page).count()).toBeGreaterThanOrEqual(1);
    await expect(all.first()).not.toHaveAttribute("data-lit", "true");
    await expect(field(page)).toHaveAttribute("data-light", "true");
    const dimmed = field(page).locator('button:not([data-lit="true"])').last();
    await expect.poll(() => dimmed.evaluate((el) => Number(getComputedStyle(el).opacity))).toBeLessThan(1);
    await page.mouse.move(0, 0);
    await expect(lit(page)).toHaveCount(0);
    await expect(field(page)).toHaveAttribute("data-light", "false");

    await all.first().focus();
    await expect(lit(page).first()).toBeVisible();
    await page.keyboard.press("Tab");
    await expect(lit(page)).toHaveCount(0);
  });

  test("Enter pins a square and shows its place card, and Escape clears it", async ({ page }) => {
    const first = squares(page).first();
    const ref = await refOf(first);
    await expect(card(page)).toContainText("Crosswalk");

    await first.focus();
    await page.keyboard.press("Enter");
    await expect(first).toHaveAttribute("aria-pressed", "true");
    await expect(card(page)).toContainText(ref);
    await expect(card(page)).toContainText("ISO/IEC 27001");
    await expect(card(page)).toContainText(/Readiness\s*\d+/);
    await expect(card(page)).toContainText("Also answers");
    await expect(card(page).getByRole("link", { name: /Open control/ })).toBeVisible();
    const answers = Number((await card(page).textContent()).match(/Also answers\s*(\d+) controls?/)[1]);
    expect(answers).toBeGreaterThanOrEqual(1);
    await expect(lit(page)).toHaveCount(answers);
    await page.keyboard.press("Tab");
    await expect(lit(page)).toHaveCount(answers);

    const partner = card(page).getByRole("button").filter({ hasNotText: "Clear" }).first();
    await partner.click();
    await expect(first).toHaveAttribute("aria-pressed", "false");
    const pinned = field(page).locator('[aria-pressed="true"]');
    await expect(pinned).toHaveCount(1);
    expect(await refOf(pinned)).not.toBe(ref);

    await pinned.focus();
    await page.keyboard.press("Escape");
    await expect(field(page).locator('[aria-pressed="true"]')).toHaveCount(0);
    await expect(lit(page)).toHaveCount(0);
    await expect(card(page)).toContainText("Crosswalk");
    await expect(card(page).getByRole("link", { name: /Open control/ })).toHaveCount(0);

    await first.focus();
    await page.keyboard.press("Enter");
    await expect(first).toHaveAttribute("aria-pressed", "true");
    await page.keyboard.press("Enter");
    await expect(first).toHaveAttribute("aria-pressed", "false");
  });

  test("Open control in the place card lands on the register with that control open", async ({ page }) => {
    const first = squares(page).first();
    const ref = await refOf(first);
    await first.focus();
    await page.keyboard.press("Enter");
    await card(page).getByRole("link", { name: /Open control/ }).click();
    await expect(page).toHaveURL(new RegExp(`/controls\\?framework=iso27001&search=${ref.replace(/\./g, "\\.")}$`));
    await expect(page.getByRole("tab", { name: /^ISO\/IEC 27001/ })).toHaveAttribute("aria-selected", "true");
    await expect(page.getByLabel("Search controls", { exact: true })).toHaveValue(ref);
    await expect(page.getByRole("main").locator('[aria-expanded="true"]').first()).toContainText(ref);
  });
});

test.describe("documents", () => {
  test("the folder tree lists all three seeded frameworks", async ({ page }) => {
    await open(page, "/documents", "Documents");
    for (const framework of ["ISO-IEC 27001 2022", "PCI DSS 4.0.1", "SOC 2 2017 TSC (rev. 2022)"]) {
      await expect(page.getByText(framework, { exact: true }).first()).toBeVisible();
    }
    await expect(page.getByText("Select a folder", { exact: true })).toBeVisible();
  });

  test("selecting a folder shows its documents", async ({ page }) => {
    await open(page, "/documents", "Documents");
    await page.getByText("CC6 - Logical and Physical Access Controls", { exact: true }).first().click();
    await page.waitForLoadState("networkidle");
    await expect(page.getByText("Select a folder", { exact: true })).toHaveCount(0);
  });

  test("choosing a file names the upload after it, unless a name was typed first", async ({ page }) => {
    await open(page, "/documents", "Documents");
    await page.getByText("CC6 - Logical and Physical Access Controls", { exact: true }).first().click();
    await page.getByRole("button", { name: "Upload document" }).click();
    const name = page.locator("#upload-name");
    const file = page.getByLabel("Document file");
    const upload = page.getByRole("button", { name: "Upload", exact: true });
    await expect(upload).toBeDisabled();
    await file.setInputFiles({ name: "Access Review Q3.pdf", mimeType: "application/pdf", buffer: Buffer.from("%PDF-1.4\n") });
    await expect(name).toHaveValue("Access Review Q3");
    await expect(upload).toBeEnabled();
    await name.fill("Quarterly access review");
    await file.setInputFiles({ name: "scan-0042.pdf", mimeType: "application/pdf", buffer: Buffer.from("%PDF-1.4\n") });
    await expect(name).toHaveValue("Quarterly access review");
    await page.getByRole("button", { name: "Cancel", exact: true }).click();
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
    await expect(page.getByRole("group", { name: "Live risks by likelihood and impact" })).toBeVisible();
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
