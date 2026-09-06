import { test, expect, open, signIn, DEMO } from "../fixtures.js";

test.describe("audit packages", () => {
  test("the seeded package shows its scope, digest and recipients", async ({ page }) => {
    await open(page, "/packages", "Audit packages");
    await expect(page.getByRole("button", { name: /SOC 2 Type II fieldwork/ })).toBeVisible();
    await expect(page.getByText("Sealed").first()).toBeVisible();

    // The digest is the whole point of sealing: it has to be on screen, with
    // the signature made by the installation's key (the seed signs), or the
    // honest note that there is none.
    const digest = page.getByText(/^[0-9a-f]{64}$/);
    await expect(digest).toBeVisible();
    await expect(page.getByText(/Ed25519, signing key|carries no signature/i)).toBeVisible();
    await expect(page.getByText("Signed", { exact: true })).toBeVisible();

    await expect(page.getByText("Management assertion")).toBeVisible();
    await expect(page.getByText("Aria Auditor").first()).toBeVisible();
    await expect(page.getByText(/Live/).first()).toBeVisible();
  });

  test("integrity is checked before the bundle can be trusted", async ({ page }) => {
    await open(page, "/packages", "Audit packages");
    await expect(page.getByText("Integrity")).toBeVisible();
    await expect(page.getByText("Every file matches what was sealed")).toBeVisible();
  });

  test("the controls in scope carry their conclusions and evidence", async ({ page }) => {
    await open(page, "/packages", "Audit packages");
    await expect(page.getByText("Controls in scope")).toBeVisible();
    await expect(page.getByText(/Design: /).first()).toBeVisible();
    await expect(page.getByText(/Operating: /).first()).toBeVisible();
    await expect(page.getByText(/nobody at this organisation can edit them/i)).toBeVisible();
  });

  test("exporting downloads a bundle", async ({ page }) => {
    await open(page, "/packages", "Audit packages");
    const download = page.waitForEvent("download");
    await page.getByRole("button", { name: /export bundle/i }).click();
    expect((await download).suggestedFilename()).toMatch(/\.zip$/);
  });

  test("the auditor sees the package and nothing else", async ({ page }) => {
    await page.goto("/login");
    await page.evaluate(() => localStorage.clear());
    await signIn(page, DEMO.auditor);

    await open(page, "/packages", "Audit packages");
    await expect(page.getByRole("button", { name: /SOC 2 Type II fieldwork/ })).toBeVisible();

    // The evidence is readable here...
    const evidence = page.getByRole("button", { name: /Policy|Procedure/ }).first();
    await expect(evidence).toBeVisible();

    // ...but the folder tree it came from is not.
    await open(page, "/documents", "Documents");
    await expect(page.getByText("Pick a folder on the left")).toBeVisible();
  });

  test("the sample workpaper shows the population and every item's result", async ({ page }) => {
    await open(page, "/packages", "Audit packages");
    await expect(page.getByText("Samples", { exact: true }).first()).toBeVisible();
    await expect(page.getByText(/Okta deprovisioning report/)).toBeVisible();
    await expect(page.getByText("u-1077", { exact: true })).toBeVisible();
    await expect(page.getByText("Exception", { exact: true }).first()).toBeVisible();
    await expect(page.getByText(/Access removed 4 business days/)).toBeVisible();
    // The organisation reads results; it never records them.
    await expect(page.getByRole("button", { name: "Pass", exact: true })).toHaveCount(0);
  });

  test("the issued auditor records a result per sampled item", async ({ page }) => {
    await page.goto("/login");
    await page.evaluate(() => localStorage.clear());
    await signIn(page, DEMO.auditor);
    await open(page, "/packages", "Audit packages");
    const item = page.locator("tr", { hasText: "u-1113" });
    await expect(item.getByText("Not yet tested", { exact: true })).toBeVisible();
    await item.getByRole("button", { name: "Pass", exact: true }).click();
    await expect(item.getByText("Aria Auditor")).toBeVisible();
    await expect(item.locator("span", { hasText: /^Pass$/ }).first()).toBeVisible();
    await expect(page.getByText(/3 pass|2 pass/)).toBeVisible();
  });

  test("a viewer sees an empty workspace rather than an error", async ({ page }) => {
    await page.goto("/login");
    await page.evaluate(() => localStorage.clear());
    await signIn(page, DEMO.viewer);
    await open(page, "/packages", "Audit packages");
    await expect(page.getByText("No packages yet")).toBeVisible();
  });
});
