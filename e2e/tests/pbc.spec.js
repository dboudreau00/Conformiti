import { test, expect, open, signIn, DEMO } from "../fixtures.js";

const list = (page) => page.getByRole("region", { name: "Request list", exact: true });
const line = (page, ref) => list(page).locator(`li[data-reference="${ref}"]`);

test.describe("PBC request list", () => {
  test("the seeded list shows every state and the organisation raises a new line", async ({ page }) => {
    await open(page, "/packages", "Audit packages");
    const panel = list(page);
    await expect(panel).toBeVisible();
    await expect(line(page, "PBC-01").getByText("Accepted", { exact: true })).toBeVisible();
    await expect(line(page, "PBC-02").getByText("Provided", { exact: true })).toBeVisible();
    await expect(line(page, "PBC-03").getByText("Open", { exact: true })).toBeVisible();
    await expect(line(page, "PBC-01").getByRole("button", { name: /Provisioning Procedure/ })).toBeVisible();

    await panel.getByRole("button", { name: "Add request" }).click();
    await panel.locator("#pbc-title").fill("Board minutes approving the security policy");
    const due = new Date(Date.now() + 7 * 86400000).toISOString().slice(0, 10);
    await panel.locator("#pbc-due").fill(due);
    await panel.locator("#pbc-assignee").selectOption({ label: "Owen Owner" });
    await panel.getByRole("button", { name: "Raise", exact: true }).click();
    await expect(page.getByText("Request raised.")).toBeVisible();
    const fresh = line(page, "PBC-04");
    await expect(fresh.getByText(/Board minutes/)).toBeVisible();
    await expect(fresh.getByText(/raised by Ada Admin \(organisation\)/)).toBeVisible();
    await expect(fresh.getByText(/assigned to Owen Owner/)).toBeVisible();
  });

  test("the issued auditor accepts a provided answer and returns nothing else", async ({ page }) => {
    await page.goto("/login");
    await page.evaluate(() => localStorage.clear());
    await signIn(page, DEMO.auditor);
    await open(page, "/packages", "Audit packages");
    const provided = line(page, "PBC-02");
    await expect(provided.getByText("Provided", { exact: true })).toBeVisible();
    // The auditor judges answers; they never mark one provided.
    await expect(provided.getByRole("button", { name: "Mark provided" })).toHaveCount(0);
    await provided.getByRole("button", { name: "Accept", exact: true }).click();
    await expect(page.getByText("PBC-02 accepted.")).toBeVisible();
    await expect(provided.getByText("Accepted", { exact: true })).toBeVisible();
    await expect(provided.getByText(/Accepted by Aria Auditor/)).toBeVisible();
  });

  test("the assignee answers from their own list without package access", async ({ page }) => {
    await page.goto("/login");
    await page.evaluate(() => localStorage.clear());
    await signIn(page, DEMO.owner);
    await open(page, "/packages", "Audit packages");
    await expect(page.getByText("No packages yet")).toBeVisible();
    const mine = page.getByRole("region", { name: "Auditor requests assigned to you", exact: true });
    await expect(mine).toBeVisible();
    const openLine = mine.locator('li[data-reference="PBC-03"]');
    await expect(openLine.getByText(/SOC 2 Type II fieldwork/)).toBeVisible();
    page.once("dialog", (d) => d.accept("Q1-Q4 sign-offs are in the access review export already in the package."));
    await openLine.getByRole("button", { name: "Mark provided" }).click();
    await expect(page.getByText("PBC-03 marked provided.")).toBeVisible();
    await expect(openLine.getByText("Provided", { exact: true })).toBeVisible();
  });
});
