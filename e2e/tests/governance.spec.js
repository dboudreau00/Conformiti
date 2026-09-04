import { test, expect, topHeading, open, expectBrowserError } from "../fixtures.js";

test.describe("audit trail", () => {
  test.beforeEach(async ({ page }) => {
    await open(page, "/audit-log", "Audit log");
  });

  test("every filter option is listed exactly once", async ({ page }) => {
    // Regression for the 0.2.0 defect where `facets` called .distinct() on a
    // queryset still carrying Meta.ordering, so -timestamp joined the SELECT
    // behind DISTINCT and every action appeared once per row.
    for (const name of ["Action", "Record type", "Actor", "Time range"]) {
      const options = await page
        .getByRole("combobox", { name, exact: true })
        .locator("option")
        .allTextContents();
      expect(options.length, `${name} has no options`).toBeGreaterThan(1);
      expect(new Set(options).size, `${name} repeats an option: ${options.join(", ")}`)
        .toBe(options.length);
    }
  });

  test("filtering by action narrows the trail", async ({ page }) => {
    const table = page.getByRole("table");
    await expect(page.getByText(/APPEND-ONLY · \d+ ENTRIES/i)).toBeVisible();
    await expect(table.getByText("DELETE").first()).toBeVisible();

    await page.getByRole("combobox", { name: "Action", exact: true }).selectOption("login");
    await page.waitForLoadState("networkidle");
    await expect(table.getByText("LOGIN").first()).toBeVisible();
    await expect(table.getByText("DELETE")).toHaveCount(0);
  });

  test("sign-ins are recorded with an actor and an address", async ({ page }) => {
    await expect(page.getByText("signed in: admin").first()).toBeVisible();
    await expect(page.getByText("127.0.0.1").first()).toBeVisible();
  });

  test("the trail is read-only through the API", async ({ page }) => {
    // Chrome logs a console error for each 405 this deliberately provokes.
    expectBrowserError(page, /status of 405/);
    // Driven from the page so it works under either transport: in cookie mode
    // the credential is an HttpOnly cookie no script -- including this one --
    // can read, so a request built outside the browser cannot carry it.
    const statuses = await page.evaluate(async () => {
      const csrf = document.cookie.match(/(?:^|; )csrftoken=([^;]*)/);
      const headers = { "Content-Type": "application/json" };
      const stored = localStorage.getItem("access");
      if (stored) headers.Authorization = `Bearer ${stored}`;
      if (csrf) headers["X-CSRFToken"] = decodeURIComponent(csrf[1]);
      const out = [];
      for (const method of ["POST", "PATCH", "DELETE"]) {
        const res = await fetch("/api/audit-log/1/", {
          method, headers, credentials: "include",
          body: JSON.stringify({ detail: "tampered" }),
        });
        out.push([method, res.status]);
      }
      return out;
    });
    for (const [method, status] of statuses) {
      expect(status, `${method} must not be allowed`).toBe(405);
    }
  });
});

test.describe("access review", () => {
  test.beforeEach(async ({ page }) => {
    await open(page, "/user-audit", "User audit");
  });

  test("the seeded review lists every user with a decision control", async ({ page }) => {
    // bootstrap_demo seeds one in-flight review; without it this screen is
    // empty on a fresh install and the README screenshot promises a view the
    // demo does not produce.
    await expect(page.getByRole("combobox", { name: /access review/i }))
      .toContainText(/access review . open \(4\/5\)/i);
    for (const name of ["Ada Admin", "Aria Auditor", "Mia Manager", "Owen Owner", "Val Viewer"]) {
      await expect(page.getByRole("radiogroup", { name: `Decision for ${name}` })).toBeVisible();
    }
    await expect(page.getByText(/5 users . 4 decided/i)).toBeVisible();
  });

  test("recording the last decision completes the attestation", async ({ page }) => {
    // Val Viewer is deliberately left pending by the seeder.
    const decision = page.getByRole("radiogroup", { name: "Decision for Val Viewer" });
    await expect(decision.getByRole("radio", { name: "Keep" })).not.toBeChecked();
    await decision.getByRole("radio", { name: "Keep" }).click();
    await page.waitForLoadState("networkidle");
    await expect(page.getByText(/5 users . 5 decided/i)).toBeVisible();
    await expect(page.getByRole("button", { name: /complete review/i })).toBeEnabled();
  });

  test("exporting the review downloads a CSV", async ({ page }) => {
    const download = page.waitForEvent("download");
    await page.getByRole("button", { name: /export csv/i }).click();
    expect((await download).suggestedFilename()).toMatch(/\.csv$/);
  });

  test("starting a new review snapshots every account again", async ({ page }) => {
    await page.getByRole("textbox", { name: /new review name/i }).fill("E2E interim review");
    await page.getByRole("button", { name: /start new review/i }).click();
    await page.waitForLoadState("networkidle");
    await expect(page.getByRole("combobox", { name: /access review/i }))
      .toContainText("E2E interim review");
    await expect(page.getByRole("radiogroup", { name: "Decision for Ada Admin" })).toBeVisible();
  });
});

test.describe("users, meetings and groups", () => {
  test("the user list shows every demo account and its role", async ({ page }) => {
    await open(page, "/users", "Users");
    // Role also appears in each row's hidden <select>, so match cells.
    for (const role of ["Compliance Manager", "Control Owner", "Auditor"]) {
      await expect(page.getByRole("cell", { name: role, exact: true }).first()).toBeVisible();
    }
  });

  test("meetings show the seeded series and their minutes", async ({ page }) => {
    await open(page, "/meetings", "Meetings");
    await expect(page.getByText("Security Steering Committee").first()).toBeVisible();
    await expect(page.getByText("Risk Review").first()).toBeVisible();
  });

  test("champion groups list their members", async ({ page }) => {
    await open(page, "/groups", "Champion groups");
    await expect(page.getByText("Security Champions").first()).toBeVisible();
  });
});
