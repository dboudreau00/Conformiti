import { test, expect, expectBrowserError, open } from "../fixtures.js";

// Every button that saves a file from the API goes through downloadFile in
// client.js, which rejects when the download failed. These tests make sure
// each screen shows that failure instead of the button doing nothing (and,
// before the screens caught it, an unhandled rejection in the console).

// The words client.js uses when an X-Accel-Redirect reached the browser: the
// server meant nginx to send the file and no nginx was in front of it.
const UNSERVED = /MEDIA_INTERNAL=false/;

/** Answer a stored-file download the way Django does with MEDIA_INTERNAL on
 *  and no nginx in front: an empty body and the header nginx would have
 *  acted on. Returns a count of the requests it answered. */
async function withoutNginx(page, url) {
  let answered = 0;
  await page.route(url, (route) => {
    answered += 1;
    return route.fulfill({
      status: 200,
      headers: {
        "Content-Type": "application/octet-stream",
        "X-Accel-Redirect": "/protected-media/unserved",
      },
      body: "",
    });
  });
  return () => answered;
}

/** Answer an export with a server error, as a crashed view would. */
async function failing(page, url) {
  expectBrowserError(page, /status of 500/);   // the failure is the point
  await page.route(url, (route) => route.fulfill({
    status: 500,
    contentType: "text/html",
    body: "<h1>Server Error (500)</h1>",
  }));
}

/** How many downloads the browser has started, so a test can say none was. */
function downloads(page) {
  let started = 0;
  page.on("download", () => { started += 1; });
  return () => started;
}

const alertSaying = (page, text) => page.getByRole("alert").filter({ hasText: text });

test.describe("a stored file that no nginx sends", () => {
  test("a document download says why, from the folder list and from search", async ({ page }) => {
    const saved = downloads(page);
    const answered = await withoutNginx(page, /\/api\/documents\/\d+\/download\/$/);
    await open(page, "/documents", "Documents");
    for (const label of [/SOC 2/i, /^CC6\b/i, /CC6\.1/i]) {
      await page.getByRole("treeitem", { name: label }).first().click();
    }
    await page.waitForLoadState("networkidle");

    await page.getByRole("button", { name: "Download Access Control Policy", exact: true }).first().click();
    await expect(alertSaying(page, UNSERVED)).toBeVisible();
    expect(answered()).toBe(1);

    // A fresh page, so the alert below can only come from the search row.
    await page.reload();
    await page.waitForLoadState("networkidle");
    await expect(page.getByRole("alert").filter({ hasText: UNSERVED })).toHaveCount(0);
    await page.getByLabel("Search documents", { exact: true }).fill("Access Control Policy");
    const results = page.getByRole("region", { name: "Search results" });
    await results.getByRole("button", { name: "Download Access Control Policy", exact: true }).first().click();
    await expect.poll(answered).toBe(2);
    await expect(alertSaying(page, UNSERVED)).toBeVisible();
    // The empty body was never saved as a 0-byte file.
    expect(saved()).toBe(0);
  });

  test("a meeting's minutes file says why", async ({ page }) => {
    const saved = downloads(page);
    const answered = await withoutNginx(page, /\/api\/meeting-minutes\/\d+\/download\/$/);
    await open(page, "/meetings", "Meetings");
    // The seeded minutes carry no file, so record one that does.
    await page.locator("#mm-date").fill(new Date().toISOString().slice(0, 10));
    await page.locator("#mm-title").fill("E2E minutes with a file");
    await page.locator("#mm-file").setInputFiles({
      name: "minutes.txt",
      mimeType: "text/plain",
      buffer: Buffer.from("Decisions: none.\n"),
    });
    await page.getByRole("button", { name: "Save minutes" }).click();
    await expect(page.getByText(/^Minutes recorded for /)).toBeVisible();

    const row = page.getByRole("listitem").filter({ hasText: "E2E minutes with a file" });
    await row.getByRole("button", { name: "Open file" }).click();
    await expect(alertSaying(page, UNSERVED)).toBeVisible();
    expect(answered()).toBe(1);
    expect(saved()).toBe(0);
  });
});

test.describe("a CSV export the server fails", () => {
  test("the responsibility matrix says the export failed", async ({ page }) => {
    await failing(page, /\/api\/responsibilities\/export\//);
    await open(page, "/responsibilities", "Responsibility matrix");
    await page.getByRole("button", { name: "Export", exact: true }).click();
    await expect(alertSaying(page, "Couldn't export the responsibility matrix.")).toBeVisible();
  });

  test("a vendor's matrix says the export failed", async ({ page }) => {
    await failing(page, /\/api\/vendors\/\d+\/matrix\/export\//);
    await open(page, "/vendors", "Vendors");
    await page.getByRole("button", { name: /Amazon Web Services/ }).click();
    await page.getByRole("tab", { name: "Responsibility matrix", exact: true }).click();
    await page.getByRole("button", { name: "Export", exact: true }).click();
    await expect(alertSaying(page, "Couldn't export the responsibility matrix.")).toBeVisible();
  });

  test("a package's request list says the export failed", async ({ page }) => {
    await failing(page, /\/api\/pbc-requests\/export\//);
    await open(page, "/packages", "Audit packages");
    const list = page.getByRole("region", { name: "Request list", exact: true });
    await list.getByRole("button", { name: "CSV", exact: true }).click();
    await expect(alertSaying(page, "Couldn't export the request list.")).toBeVisible();
  });
});
