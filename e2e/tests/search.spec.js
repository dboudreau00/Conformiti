import { test, expect, DEMO, signIn, forgetSession, open, searchButton } from "../fixtures.js";

/**
 * The search palette: Ctrl K (Cmd K on a Mac) or the button in the top bar.
 * One input, three existing list endpoints (controls, documents, people),
 * grouped results, and a link to the record's own page that the page reads
 * from its address. It asks only what the signed-in role may list, so what it
 * shows is never something the API would refuse.
 */

const palette = (page) => page.getByRole("dialog", { name: "Jump to" });
const field = (page) => palette(page).getByRole("combobox", { name: "Jump to a control, document or person" });
const options = (page) => palette(page).getByRole("option");
// The list area: it carries the message when there is nothing to list. The same
// words go to a live region for a screen reader, which is checked once below.
const results = (page) => palette(page).getByRole("listbox", { name: "Results" });

async function signInAs(page, persona) {
  await forgetSession(page);
  await signIn(page, persona);
}

/** The address of every API call that carried a search term. */
function watchSearches(page) {
  const seen = [];
  page.on("request", (req) => {
    const url = new URL(req.url());
    if (url.pathname.startsWith("/api/") && url.searchParams.has("search")) seen.push(url.pathname);
  });
  return seen;
}

test.describe("search palette", () => {
  test("the button and Ctrl K open it, Escape closes it and gives focus back", async ({ page }) => {
    await open(page, "/", "Dashboard");
    const button = searchButton(page);
    await expect(button).toHaveAttribute("aria-keyshortcuts", /Control\+K/);

    await button.click();
    await expect(palette(page)).toBeVisible();
    await expect(field(page)).toBeFocused();
    await page.keyboard.press("Escape");
    await expect(palette(page)).toBeHidden();
    await expect(button).toBeFocused();

    await page.keyboard.press("Control+k");
    await expect(palette(page)).toBeVisible();
    await expect(field(page)).toBeFocused();
    // Under two characters it asks nothing and says so, on screen and to a screen reader.
    await expect(results(page)).toContainText("Type 2 or more characters.");
    await expect(palette(page).getByRole("status")).toHaveText("Type 2 or more characters.");
    await page.keyboard.press("Escape");
    await expect(palette(page)).toBeHidden();
  });

  test("a control reference finds the control and Enter opens it on the register", async ({ page }) => {
    await open(page, "/", "Dashboard");
    await page.keyboard.press("Control+k");
    await field(page).fill("CC6.1");

    const controls = palette(page).getByRole("group", { name: "Controls" });
    const first = controls.getByRole("option").first();
    await expect(first).toBeVisible();
    // The reference that equals the query ranks first.
    await expect(first).toContainText(/^CC6\.1/);
    await expect(first).toHaveAttribute("aria-selected", "true");

    // The arrow keys move through the results and wrap.
    const all = options(page);
    expect(await all.count()).toBeGreaterThan(1);
    await page.keyboard.press("ArrowDown");
    await expect(first).toHaveAttribute("aria-selected", "false");
    await expect(all.nth(1)).toHaveAttribute("aria-selected", "true");
    await page.keyboard.press("ArrowUp");
    await expect(first).toHaveAttribute("aria-selected", "true");

    await page.keyboard.press("Enter");
    await expect(palette(page)).toBeHidden();
    // The reference is not unique across frameworks, so the link names both.
    await expect(page).toHaveURL(/\/controls\?framework=[^&]+&search=CC6\.1$/);
    await expect(page.getByRole("main").getByRole("heading", { name: "Controls", level: 1, exact: true })).toBeVisible();
    // The page read the address: the framework's tab, the search box and the
    // control itself, opened.
    await expect(page.getByRole("tab", { name: /SOC 2/ })).toHaveAttribute("aria-selected", "true");
    await expect(page.getByLabel("Search controls", { exact: true })).toHaveValue("CC6.1");
    const row = page.getByRole("main").locator('[aria-expanded="true"]').first();
    await expect(row).toContainText("CC6.1");
  });

  test("a document name finds the document and Enter opens the Documents page searched", async ({ page }) => {
    await open(page, "/", "Dashboard");
    await page.keyboard.press("Control+k");
    await field(page).fill("Penetration Test Report");

    const group = palette(page).getByRole("group", { name: "Documents" });
    const hit = group.getByRole("option", { name: /Penetration Test Report/ });
    await expect(hit).toBeVisible();
    // Walk to it with the arrow keys, wherever it sits among the results.
    const at = await options(page).evaluateAll(
      (els) => els.findIndex((el) => /Penetration Test Report/.test(el.textContent))
    );
    for (let i = 0; i < at; i += 1) await page.keyboard.press("ArrowDown");
    await expect(hit).toHaveAttribute("aria-selected", "true");

    await page.keyboard.press("Enter");
    await expect(palette(page)).toBeHidden();
    await expect(page).toHaveURL(/\/documents\?search=Penetration%20Test%20Report$/);
    await expect(page.getByLabel("Search documents", { exact: true })).toHaveValue("Penetration Test Report");
    await expect(page.getByRole("main").getByRole("button", { name: "Penetration Test Report", exact: true }).first()).toBeVisible();
  });

  test("an administrator also finds people, and the click lands on the Users page filtered", async ({ page }) => {
    await open(page, "/", "Dashboard");
    await page.keyboard.press("Control+k");
    await field(page).fill("Ada Admin");

    const person = palette(page).getByRole("group", { name: "People" }).getByRole("option", { name: /Ada Admin/ });
    await expect(person).toBeVisible();
    await person.click();
    await expect(palette(page)).toBeHidden();
    await expect(page).toHaveURL(/\/users\?search=admin$/);
    await expect(page.getByLabel("Search users", { exact: true })).toHaveValue("admin");
    await expect(page.getByRole("main").getByText("Ada Admin").first()).toBeVisible();
  });

  test("a term that matches nothing says so, and a short one asks nothing", async ({ page }) => {
    const searched = watchSearches(page);
    await open(page, "/", "Dashboard");
    await page.keyboard.press("Control+k");
    await field(page).fill("q");
    await expect(results(page)).toContainText("Type 2 or more characters.");
    await page.waitForTimeout(500);
    expect(searched).toEqual([]);

    await field(page).fill("zzqqxx");
    await expect(results(page)).toContainText('Nothing matches "zzqqxx".');
    await expect(options(page)).toHaveCount(0);
    // Controls, documents and people: one request each, no more.
    expect(searched.sort()).toEqual(["/api/controls/", "/api/documents/", "/api/users/"]);
  });

  test("a viewer is offered controls, and people are never asked for", async ({ page }) => {
    await signInAs(page, DEMO.viewer);
    await open(page, "/", "Dashboard");
    const searched = watchSearches(page);
    await page.keyboard.press("Control+k");
    await field(page).fill("access");
    await expect(palette(page).getByRole("group", { name: "Controls" })).toBeVisible();
    await expect(palette(page).getByRole("group", { name: "People" })).toHaveCount(0);
    // Controls and documents are asked for (the viewer has no folder holding a
    // match, so documents comes back empty and is left out of the list); the
    // user directory is not, because the Users page is not theirs to open.
    expect([...searched].sort()).toEqual(["/api/controls/", "/api/documents/"]);
  });

  test("an external auditor is offered documents only, and nothing else is asked for", async ({ page }) => {
    await signInAs(page, DEMO.auditor);
    await open(page, "/packages", "Audit packages");
    const searched = watchSearches(page);
    await page.keyboard.press("Control+k");
    await field(page).fill("policy");
    await expect(palette(page).getByRole("group", { name: "Documents" })).toBeVisible();
    await expect(palette(page).getByRole("group", { name: "Controls" })).toHaveCount(0);
    await expect(palette(page).getByRole("group", { name: "People" })).toHaveCount(0);
    // The API refuses an auditor the control library and the user directory,
    // so the palette must not so much as ask.
    expect(searched).toEqual(["/api/documents/"]);
  });
});
