import { test, expect, open, expectBrowserError } from "../fixtures.js";

test.describe("audit trail", () => {
  test.beforeEach(async ({ page }) => {
    await open(page, "/audit-log", "Audit log");
  });

  test("every filter option is listed exactly once", async ({ page }) => {
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
    await expect(page.getByText(/^[\d,]+ entries$/i)).toBeVisible();
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
    expectBrowserError(page, /status of 405/);
    // Driven from the page so it works under either transport: in cookie mode the credential is an
    // HttpOnly cookie, so a request built outside the browser cannot carry it.
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
    await expect(page.getByRole("combobox", { name: /access review/i }))
      .toContainText(/access review, open \(4\/5\)/i);
    for (const name of ["Ada Admin", "Aria Auditor", "Mia Manager", "Owen Owner", "Val Viewer"]) {
      await expect(page.getByRole("radiogroup", { name: `Decision for ${name}` })).toBeVisible();
    }
    await expect(page.getByText(/4\/5 decided/i)).toBeVisible();
  });

  test("recording the last decision completes the attestation", async ({ page }) => {
    const decision = page.getByRole("radiogroup", { name: "Decision for Val Viewer" });
    await expect(decision.getByRole("radio", { name: "Keep" })).not.toBeChecked();
    await decision.getByRole("radio", { name: "Keep" }).click();
    await page.waitForLoadState("networkidle");
    await expect(page.getByText(/5\/5 decided/i)).toBeVisible();
    await expect(page.getByRole("button", { name: /complete review/i })).toBeEnabled();
  });

  test("exporting the review downloads a CSV", async ({ page }) => {
    const download = page.waitForEvent("download");
    await page.getByRole("button", { name: /export csv/i }).click();
    expect((await download).suggestedFilename()).toMatch(/\.csv$/);
  });

  test("the decision is one radio group: a single tab stop, and the arrow keys choose", async ({ page }) => {
    const group = page.getByRole("radiogroup", { name: "Decision for Owen Owner" });
    const modify = group.getByRole("radio", { name: "Modify" });
    const revoke = group.getByRole("radio", { name: "Revoke" });
    await expect(modify).toBeChecked();
    await expect(group.locator('[role="radio"][tabindex="0"]')).toHaveCount(1);
    await expect(modify).toHaveAttribute("tabindex", "0");

    await modify.focus();
    await page.keyboard.press("ArrowRight");
    await expect(revoke).toBeChecked();
    await expect(revoke).toBeFocused();
    // Back to the seeded choice, so the rest of the suite sees the review as it was.
    await page.keyboard.press("ArrowLeft");
    await expect(modify).toBeChecked();
    await expect(modify).toBeFocused();
    await page.waitForLoadState("networkidle");
  });

  test("the rows are a table with a header for each column", async ({ page }) => {
    const table = page.getByRole("table");
    for (const name of ["User", "Role", "Capabilities", "Decision", "Notes"]) {
      await expect(table.getByRole("columnheader", { name, exact: true })).toBeVisible();
    }
    await expect(table.getByRole("row", { name: /Ada Admin/ }).first()).toBeVisible();
  });

  test("creating a review snapshots every account again", async ({ page }) => {
    await page.getByRole("textbox", { name: /new review name/i }).fill("E2E interim review");
    await page.getByRole("button", { name: /create review/i }).click();
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

  test("an inline champion edit saves on Enter and closes on Escape", async ({ page }) => {
    await open(page, "/groups", "Champion groups");
    const edit = page.getByRole("button", { name: /^Edit Val Viewer in / });
    const note = page.getByRole("textbox", { name: "Note for Val Viewer" });

    await edit.click();
    await note.fill("typed, then abandoned");
    await note.press("Escape");
    await expect(note).toHaveCount(0);
    await expect(page.getByText("typed, then abandoned")).toHaveCount(0);

    await edit.click();
    await note.fill("E2E keyboard save");
    await note.press("Enter");
    await expect(note).toHaveCount(0);
    await expect(page.getByText("E2E keyboard save")).toBeVisible();

    // Back to the seeded (empty) note, by the same keys.
    await edit.click();
    await note.fill("");
    await note.press("Enter");
    await expect(note).toHaveCount(0);
    await expect(page.getByText("E2E keyboard save")).toHaveCount(0);
  });
});

test.describe("when a list fails to load", () => {
  // Chrome logs one console error for every non-2xx response, so the suite is told to expect it.
  async function failUntilHealed(page, pattern) {
    expectBrowserError(page, /status of 500/);
    let failing = true;
    await page.route(pattern, (route) => {
      if (!failing || route.request().method() !== "GET") return route.continue();
      return route.fulfill({ status: 500, contentType: "application/json", body: "{}" });
    });
    return () => { failing = false; };
  }

  test("the user list says so, not that there are no users, and Try again recovers", async ({ page }) => {
    const heal = await failUntilHealed(page, /\/api\/users\/(\?.*)?$/);
    await page.goto("/users");
    await expect(page.getByText("The user list could not be loaded")).toBeVisible();
    await expect(page.getByText("No users yet")).toHaveCount(0);

    heal();
    await page.getByRole("button", { name: "Try again" }).click();
    await expect(page.getByRole("region", { name: "Users", exact: true })).toBeVisible();
    await expect(page.getByText("The user list could not be loaded")).toHaveCount(0);
  });

  test("the champion groups say so, not that there are none, and Try again recovers", async ({ page }) => {
    const heal = await failUntilHealed(page, /\/api\/champion-groups\/(\?.*)?$/);
    await page.goto("/groups");
    await expect(page.getByText("The champion groups could not be loaded")).toBeVisible();
    await expect(page.getByText("No champion groups yet")).toHaveCount(0);
    await expect(page.getByText("No group selected")).toHaveCount(0);

    heal();
    await page.getByRole("button", { name: "Try again" }).click();
    await expect(page.getByText("Security Champions").first()).toBeVisible();
  });

  test("the access reviews say so, not that there are none, and Try again recovers", async ({ page }) => {
    const heal = await failUntilHealed(page, /\/api\/access-reviews\/(\?.*)?$/);
    await page.goto("/user-audit");
    await expect(page.getByText("The access reviews could not be loaded")).toBeVisible();
    await expect(page.getByText("No access reviews yet")).toHaveCount(0);

    heal();
    await page.getByRole("button", { name: "Try again" }).click();
    await expect(page.getByRole("radiogroup", { name: "Decision for Ada Admin" })).toBeVisible();
  });

  test("the rows of a review say so, not that it has none, and Try again recovers", async ({ page }) => {
    const heal = await failUntilHealed(page, /\/api\/access-review-items\/\?review=\d+$/);
    await page.goto("/user-audit");
    await expect(page.getByText("The review rows could not be loaded")).toBeVisible();
    await expect(page.getByText("No rows in this review")).toHaveCount(0);
    await expect(page.getByRole("button", { name: /complete review/i })).toBeDisabled();

    heal();
    await page.getByRole("button", { name: "Try again" }).click();
    await expect(page.getByRole("radiogroup", { name: "Decision for Ada Admin" })).toBeVisible();
  });

  test("a failed first page of the audit trail is told once", async ({ page }) => {
    const heal = await failUntilHealed(page, /\/api\/audit-log\/\?page=1/);
    await page.goto("/audit-log");
    await expect(page.getByText("The audit trail could not be loaded")).toBeVisible();
    // The reason is in the panel; a banner above it would say the same again.
    await expect(page.getByText("The server had a problem. Try again in a moment.")).toHaveCount(1);

    heal();
    await page.getByRole("button", { name: "Try again" }).click();
    await expect(page.getByRole("table")).toBeVisible();
  });
});

test.describe("destructive confirmations", () => {
  const rgb = (page, token) => page.evaluate((name) =>
    `rgb(${getComputedStyle(document.documentElement).getPropertyValue(name).trim().split(" ").join(", ")})`, token);

  test("the confirm is the heavy button and Close sits inside the Tab cycle", async ({ page }) => {
    await open(page, "/groups", "Champion groups");
    await page.getByRole("button", { name: "Delete group", exact: true }).click();
    const dialog = page.getByRole("dialog", { name: /^Delete .+\?$/ });
    await expect(dialog).toBeVisible();
    const close = dialog.getByRole("button", { name: "Close", exact: true });
    const cancel = dialog.getByRole("button", { name: "Cancel", exact: true });
    const confirm = dialog.getByRole("button", { name: "Delete group", exact: true });

    await expect(confirm).toHaveCSS("background-color", await rgb(page, "--danger"));
    await expect(confirm).toHaveCSS("color", await rgb(page, "--danger-ink"));

    await expect(cancel).toBeFocused();
    await page.keyboard.press("Shift+Tab");
    await expect(close).toBeFocused();
    await page.keyboard.press("Shift+Tab");
    await expect(confirm).toBeFocused();
    await page.keyboard.press("Tab");
    await expect(close).toBeFocused();
    await page.keyboard.press("Tab");
    await expect(cancel).toBeFocused();

    await cancel.click();
    await expect(dialog).toBeHidden();
  });

  test("a confirm shows its work in the button and leaves the label alone", async ({ page }) => {
    await open(page, "/groups", "Champion groups");
    // A group of its own, so the seeded one stays for everything else.
    await page.locator("#cg-name").fill("E2E busy check");
    await page.getByRole("button", { name: "Create group", exact: true }).click();
    await expect(page.getByRole("heading", { name: "E2E busy check", level: 2 })).toBeVisible();

    // Hold the delete until the button has been looked at.
    let release;
    const gate = new Promise((resolve) => { release = resolve; });
    await page.route(/\/api\/champion-groups\/\d+\/$/, async (route) => {
      if (route.request().method() !== "DELETE") return route.fallback();
      await gate;
      return route.continue();
    });
    try {
      await page.getByRole("button", { name: "Delete group", exact: true }).click();
      const dialog = page.getByRole("dialog", { name: "Delete E2E busy check?" });
      const confirm = dialog.getByRole("button", { name: "Delete group", exact: true });
      await confirm.click();

      await expect(confirm).toHaveAttribute("aria-busy", "true");
      await expect(confirm).toBeDisabled();
      await expect(confirm).toHaveText("Delete group");
      await expect(confirm.locator("svg.animate-spin")).toBeVisible();
      await expect(dialog.getByRole("button", { name: "Cancel", exact: true })).toBeDisabled();
      // `busy` is a prop, not an attribute: it must not reach the DOM.
      expect(await confirm.getAttribute("busy")).toBeNull();

      release();
      await expect(dialog).toBeHidden();
      await expect(page.getByRole("heading", { name: "E2E busy check", level: 2 })).toHaveCount(0);
    } finally {
      release();
    }
  });
});
