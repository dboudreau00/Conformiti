import { test, expect, open, signIn, DEMO } from "../fixtures.js";

test.describe("audit packages", () => {
  test("the seeded package shows its scope, digest and recipients", async ({ page }) => {
    await open(page, "/packages", "Audit packages");
    await expect(page.getByRole("button", { name: /SOC 2 Type II fieldwork/ })).toBeVisible();
    await expect(page.getByText("Sealed").first()).toBeVisible();

    // The digest is the whole point of sealing: it has to be on screen, and the
    // page must be honest that it is not a signature.
    const digest = page.getByText(/^[0-9a-f]{64}$/);
    await expect(digest).toBeVisible();
    await expect(page.getByText(/carries no signature/i)).toBeVisible();

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

  test("a viewer sees an empty workspace rather than an error", async ({ page }) => {
    await page.goto("/login");
    await page.evaluate(() => localStorage.clear());
    await signIn(page, DEMO.viewer);
    await open(page, "/packages", "Audit packages");
    await expect(page.getByText("No packages yet")).toBeVisible();
  });
});
