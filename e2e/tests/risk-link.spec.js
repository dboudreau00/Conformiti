import { test, expect, open, topHeading } from "../fixtures.js";

/** Read through the page's own credentials so it works under either transport (the header token or the cookie). */
function listRisks(page) {
  return page.evaluate(async () => {
    const headers = {};
    const stored = localStorage.getItem("access");
    if (stored) headers.Authorization = `Bearer ${stored}`;
    const res = await fetch("/api/risks/", { headers, credentials: "include" });
    const body = await res.json();
    return Array.isArray(body) ? body : body.results;
  });
}

test.describe("a link to one risk (?risk=)", () => {
  test("opens a closed risk the default live filter would hide, by widening the filter", async ({ page }) => {
    await open(page, "/risks", "Risk register");
    const closed = (await listRisks(page)).find((r) => r.status === "closed");
    expect(closed, "the demo data holds a closed risk").toBeTruthy();
    await expect(page.getByText(/3 SHOWN · 4 TOTAL/i)).toBeVisible();

    await page.goto(`/risks?risk=${closed.id}`);
    await expect(topHeading(page, "Risk register")).toBeVisible();
    await expect(page.getByRole("heading", { level: 3, name: closed.title })).toBeVisible();
    await expect(page.getByText(/4 SHOWN · 4 TOTAL/i)).toBeVisible();
  });

  test("opens a live risk without changing the filter", async ({ page }) => {
    await open(page, "/risks", "Risk register");
    const live = (await listRisks(page)).find((r) => r.status !== "closed");
    await page.goto(`/risks?risk=${live.id}`);
    await expect(topHeading(page, "Risk register")).toBeVisible();
    await expect(page.getByRole("heading", { level: 3, name: live.title })).toBeVisible();
    await expect(page.getByText(/3 SHOWN · 4 TOTAL/i)).toBeVisible();
  });

  test("a risk number that is not in the register opens the register and nothing else", async ({ page }) => {
    await page.goto("/risks?risk=999999");
    await expect(topHeading(page, "Risk register")).toBeVisible();
    await expect(page.getByText(/3 SHOWN · 4 TOTAL/i)).toBeVisible();
    await expect(page.getByRole("heading", { level: 3 })).toHaveCount(0);
  });
});
