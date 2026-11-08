import { test, expect, open } from "../fixtures.js";

const DAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
const pad = (n) => String(n).padStart(2, "0");
const ymd = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;

/** Dashboard panels are unnamed <section>s with no landmark role: anchor on the <h2> each one contains instead. */
function panel(page, heading) {
  return page.locator("section").filter({
    has: page.getByRole("heading", { name: heading, level: 2 }),
  });
}

/** Driven from the page so it works under either transport: in cookie mode the credential is an HttpOnly cookie. */
function call(page, method, path, body) {
  return page.evaluate(async ({ method, path, body }) => {
    const csrf = document.cookie.match(/(?:^|; )csrftoken=([^;]*)/);
    const headers = { "Content-Type": "application/json" };
    const stored = localStorage.getItem("access");
    if (stored) headers.Authorization = `Bearer ${stored}`;
    if (csrf) headers["X-CSRFToken"] = decodeURIComponent(csrf[1]);
    const res = await fetch(`/api${path}`, {
      method, headers, credentials: "include", body: body ? JSON.stringify(body) : undefined,
    });
    // Always read the body: a response left unread is aborted when the test ends, and the fixture counts that as a failure.
    const text = await res.text();
    let data = null;
    try { data = text ? JSON.parse(text) : null; } catch { /* not JSON */ }
    return { status: res.status, data };
  }, { method, path, body });
}

/** The first month from `from` months ahead that no event touches, so the test owns its month and no other grid shows it. */
async function emptyMonth(page, now, from) {
  for (let ahead = from; ahead < from + 24; ahead += 1) {
    const first = new Date(now.getFullYear(), now.getMonth() + ahead, 1);
    const last = new Date(now.getFullYear(), now.getMonth() + ahead + 1, 0);
    const feed = await call(page, "GET", `/calendar/feed/?start=${ymd(first)}&end=${ymd(last)}`);
    const rows = Array.isArray(feed.data) ? feed.data : feed.data?.results || [];
    if (feed.status === 200 && rows.length === 0) return ahead;
  }
  throw new Error("every one of the next 24 months already holds a calendar event");
}

test.describe("calendar events that span days", () => {
  test("an event that began before the grid sits on each visible day it runs through", async ({ page }) => {
    await open(page, "/", "Dashboard");
    const now = new Date();
    const ahead = await emptyMonth(page, now, 3);
    const target = new Date(now.getFullYear(), now.getMonth() + ahead, 1);
    const month = `${MONTHS[target.getMonth()]} ${target.getFullYear()}`;

    // It starts on the 15th of the month before: earlier than the first cell of the target month's grid.
    const title = `Fieldwork window ${now.getTime()}`;
    const created = await call(page, "POST", "/calendar/", {
      title,
      event_type: "custom",
      all_day: true,
      date: ymd(new Date(target.getFullYear(), target.getMonth() - 1, 15)),
      end_date: ymd(new Date(target.getFullYear(), target.getMonth(), 2)),
    });
    expect(created.status).toBe(201);
    try {
      const calendar = panel(page, "Compliance calendar");
      for (let i = 0; i < ahead; i += 1) await calendar.getByRole("button", { name: "Next month", exact: true }).click();
      await expect(calendar.getByText(month, { exact: true })).toBeVisible();

      const cell = (day) => calendar.getByRole("button", {
        name: new RegExp(`, ${day} ${month}, \\d+ items?$`),
      });
      await expect(cell(1).locator(`[title="${title}"]`)).toBeVisible();
      await expect(cell(2).locator(`[title="${title}"]`)).toBeVisible();
      await expect(cell(3).locator(`[title="${title}"]`)).toHaveCount(0);
      // It began last month and still counts for this one: the month held nothing else.
      await expect(calendar.getByText(/^\d+ items? this month$/)).toHaveText("1 item this month");

      await cell(2).click();
      await expect(calendar.getByRole("listitem").filter({ hasText: title }))
        .toContainText(`until ${DAYS[new Date(target.getFullYear(), target.getMonth(), 2).getDay()]} 2 ${MONTHS[target.getMonth()]} ${target.getFullYear()}`);
    } finally {
      await call(page, "DELETE", `/calendar/${created.data.id}/`);
    }
  });
});
