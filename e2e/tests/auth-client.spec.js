// The SPA's sign-in plumbing (frontend/src/api/client.js) run in Node against a scripted server: no browser, so a
// second tab, a dropped connection and an expired access token can be staged exactly. The real-browser counterpart
// is auth-session.spec.js.
import { test, expect } from "@playwright/test";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const FRONTEND = path.resolve(HERE, "..", "..", "frontend");
const url = (...parts) => pathToFileURL(path.join(FRONTEND, ...parts)).href;

// Same file as client.js's own `import axios from "axios"`, so setting its default adapter reaches every call.
const { default: axios } = await import(url("node_modules", "axios", "index.js"));

class FakeStorage {
  constructor(initial = {}) { this.map = new Map(Object.entries(initial)); }
  getItem(k) { return this.map.has(k) ? this.map.get(k) : null; }
  setItem(k, v) { this.map.set(k, String(v)); }
  removeItem(k) { this.map.delete(k); }
}

let loads = 0;

// One worker runs every spec, so the fakes this file installs must not outlive it.
const ORIGINAL = {
  localStorage: globalThis.localStorage, document: globalThis.document, window: globalThis.window,
  adapter: axios.defaults.adapter,
};
test.afterAll(() => {
  for (const name of ["localStorage", "document", "window"]) {
    if (ORIGINAL[name] === undefined) delete globalThis[name];
    else globalThis[name] = ORIGINAL[name];
  }
  axios.defaults.adapter = ORIGINAL.adapter;
});

/** A fresh copy of client.js (its transport is module state) wired to `routes`: "METHOD /full/path" -> (call) =>
 * [status, body] or throws for a dropped connection. Every call is logged. */
async function load({ routes, storage = {}, cookies = "csrftoken=tok", mode = "header" }) {
  const calls = [];
  globalThis.localStorage = new FakeStorage(storage);
  globalThis.document = { cookie: cookies };
  globalThis.window = { location: { pathname: "/controls", href: "/controls" } };
  const adapter = async (config) => {
    const base = config.baseURL && !config.url.startsWith("/api/") ? config.baseURL : "";
    const full = `${config.method.toUpperCase()} ${base}${config.url}`;
    const call = {
      full, body: config.data ? JSON.parse(config.data) : null, headers: { ...config.headers.toJSON() },
    };
    calls.push(call);
    const handler = routes[full];
    if (!handler) throw new Error(`unscripted request: ${full}`);
    const [status, data] = handler(call);
    const response = { data, status, statusText: String(status), headers: {}, config, request: {} };
    if (status >= 200 && status < 300) return response;
    throw new axios.AxiosError(`status ${status}`, "ERR_BAD_REQUEST", config, {}, response);
  };
  axios.defaults.adapter = adapter;
  const client = await import(`${url("src", "api", "client.js")}?load=${++loads}`);
  routes["GET /api/auth/config/"] = () => [200, { transport: mode }];
  await client.loadAuthConfig();
  calls.length = 0;
  return { client, calls, storage: globalThis.localStorage, window: globalThis.window };
}

const dropped = () => { throw new axios.AxiosError("Network Error", "ERR_NETWORK"); };

test.describe("sign-in plumbing", () => {
  test("WEB-04: a refused password leaves the session in the other tab alone", async () => {
    const { client, storage, calls } = await load({
      storage: { access: "A1", refresh: "R1", workspace: "acme" },
      routes: { "POST /api/auth/token/": () => [400, { detail: "No active account found." }] },
    });
    await expect(client.login("admin", "wrong")).rejects.toBeTruthy();
    expect(storage.getItem("access")).toBe("A1");
    expect(storage.getItem("refresh")).toBe("R1");
    expect(storage.getItem("workspace")).toBe("acme");
    expect(calls.map((c) => c.full)).toEqual(["POST /api/auth/token/"]);
  });

  test("WEB-04: a second factor still owed changes nothing either", async () => {
    const { client, storage } = await load({
      storage: { access: "A1", refresh: "R1", workspace: "acme" },
      routes: { "POST /api/auth/token/": () => [400, { mfa_required: true, factors: { totp: true } }] },
    });
    await expect(client.login("admin", "right")).rejects.toBeTruthy();
    expect([storage.getItem("access"), storage.getItem("refresh"), storage.getItem("workspace")])
      .toEqual(["A1", "R1", "acme"]);
  });

  test("WEB-04: an accepted sign-in replaces the principal and revokes the refresh token it displaced", async () => {
    const { client, storage, calls } = await load({
      storage: { access: "A1", refresh: "R1", workspace: "acme" },
      routes: {
        "POST /api/auth/token/": () => [200, { access: "A2", refresh: "R2" }],
        "POST /api/auth/token/clear/": () => [200, { revoked: 1 }],
      },
    });
    await client.login("admin", "right");
    expect([storage.getItem("access"), storage.getItem("refresh"), storage.getItem("workspace")])
      .toEqual(["A2", "R2", null]);
    // The revoke is sent without being awaited, so wait for it to arrive rather than for a fixed time.
    await expect.poll(() => calls.some((c) => c.full === "POST /api/auth/token/clear/")).toBe(true);
    const revoke = calls.find((c) => c.full === "POST /api/auth/token/clear/");
    expect(revoke.body).toEqual({ refresh: "R1" });
    expect(revoke.headers.Authorization).toBeUndefined();
  });

  test("WEB-03: single sign-on forgets the previous superuser's workspace once it is accepted", async () => {
    const { client, storage } = await load({
      storage: { access: "A1", refresh: "R1", workspace: "secret" },
      routes: {
        "POST /api/auth/oidc/redeem/": (call) => (call.body.otp
          ? [200, { access: "A2", refresh: "R2" }]
          : [200, { mfa_required: true, factors: { totp: true } }]),
        "POST /api/auth/token/clear/": () => [200, {}],
      },
    });
    // The challenge is not an acceptance: the choice, and the other tab's tokens, stay.
    const challenge = await client.redeemSso("ticket");
    expect(challenge.mfa_required).toBe(true);
    expect(storage.getItem("workspace")).toBe("secret");
    expect(storage.getItem("access")).toBe("A1");
    await client.redeemSso("ticket", "123456");
    expect(storage.getItem("workspace")).toBeNull();
    expect([storage.getItem("access"), storage.getItem("refresh")]).toEqual(["A2", "R2"]);
  });

  test("WEB-03: in cookie mode the workspace is cleared too and no token reaches script", async () => {
    const { client, storage } = await load({
      mode: "cookie",
      storage: { workspace: "secret" },
      routes: { "POST /api/auth/oidc/redeem/": () => [200, { authenticated: true }] },
    });
    await client.redeemSso("ticket");
    expect(storage.getItem("workspace")).toBeNull();
    expect(storage.getItem("access")).toBeNull();
  });
});

test.describe("sign-out", () => {
  test("WEB-02: an expired access token does not stop the refresh token being revoked", async () => {
    const { client, storage, calls } = await load({
      storage: { access: "stale", refresh: "R1", workspace: "acme" },
      routes: {
        "POST /api/auth/logout/": () => [401, { detail: "Token is expired" }],
        "POST /api/auth/token/clear/": () => [200, { revoked: 1 }],
      },
    });
    await client.logout();
    const clear = calls.find((c) => c.full === "POST /api/auth/token/clear/");
    expect(clear, "the refresh token must be sent on").toBeTruthy();
    expect(clear.body).toEqual({ refresh: "R1" });
    expect(clear.headers.Authorization, "a dead Bearer would be refused before the view").toBeUndefined();
    expect([storage.getItem("access"), storage.getItem("refresh"), storage.getItem("workspace")])
      .toEqual([null, null, null]);
  });

  test("WEB-02: a live session signs out in the one authenticated call", async () => {
    const { client, calls } = await load({
      storage: { access: "A1", refresh: "R1" },
      routes: { "POST /api/auth/logout/": () => [200, { refresh_revoked: true }] },
    });
    await client.logout();
    expect(calls.map((c) => c.full)).toEqual(["POST /api/auth/logout/"]);
  });

  test("WEB-02: an offline sign-out still clears the browser", async () => {
    const { client, storage } = await load({
      storage: { access: "A1", refresh: "R1" },
      routes: { "POST /api/auth/logout/": dropped },
    });
    await client.logout();
    expect(storage.getItem("refresh")).toBeNull();
  });
});

test.describe("a refused request", () => {
  test("WEB-05: a refresh another tab won is not a sign-out", async () => {
    let served = 0;
    const routes = {
      "GET /api/controls/": (call) => {
        served += 1;
        return call.headers.Authorization === "Bearer A2" ? [200, { ok: true }] : [401, {}];
      },
      "POST /api/auth/token/refresh/": () => {
        // The other tab's rotation lands first: this tab's token is now blacklisted, and storage holds the new pair.
        localStorage.setItem("access", "A2");
        localStorage.setItem("refresh", "R2");
        return [401, { detail: "Token is blacklisted" }];
      },
    };
    const { client, storage, window } = await load({ storage: { access: "A1", refresh: "R1", workspace: "acme" }, routes });
    const r = await client.default.get("/controls/");
    expect(r.data).toEqual({ ok: true });
    expect(served).toBe(2);
    expect([storage.getItem("access"), storage.getItem("refresh"), storage.getItem("workspace")])
      .toEqual(["A2", "R2", "acme"]);
    expect(window.location.href).toBe("/controls");
  });

  test("WEB-05: a dropped connection during the refresh keeps the session and the workspace", async () => {
    const { client, storage, window } = await load({
      storage: { access: "A1", refresh: "R1", workspace: "acme" },
      routes: { "GET /api/controls/": () => [401, {}], "POST /api/auth/token/refresh/": dropped },
    });
    await expect(client.default.get("/controls/")).rejects.toMatchObject({ response: { status: 401 } });
    expect([storage.getItem("access"), storage.getItem("refresh"), storage.getItem("workspace")])
      .toEqual(["A1", "R1", "acme"]);
    expect(window.location.href).toBe("/controls");
  });

  test("WEB-05: a busy server (5xx) is not a refusal either", async () => {
    const { client, storage } = await load({
      storage: { access: "A1", refresh: "R1" },
      routes: { "GET /api/controls/": () => [401, {}], "POST /api/auth/token/refresh/": () => [503, {}] },
    });
    await expect(client.default.get("/controls/")).rejects.toBeTruthy();
    expect(storage.getItem("refresh")).toBe("R1");
  });

  test("WEB-05: a token the server really refuses signs out, and keeps the workspace choice", async () => {
    const { client, storage, window } = await load({
      storage: { access: "A1", refresh: "R1", workspace: "acme" },
      routes: {
        "GET /api/controls/": () => [401, {}],
        "POST /api/auth/token/refresh/": () => [401, { detail: "Token is blacklisted" }],
      },
    });
    await expect(client.default.get("/controls/")).rejects.toBeTruthy();
    expect([storage.getItem("access"), storage.getItem("refresh")]).toEqual([null, null]);
    expect(storage.getItem("workspace")).toBe("acme");
    expect(window.location.href).toBe("/login");
  });

  test("WEB-05: in cookie mode a refusal that another tab already answered retries the request", async () => {
    let renewed = false;
    const { client, window } = await load({
      mode: "cookie",
      routes: {
        "GET /api/controls/": () => (renewed ? [200, { ok: true }] : [401, {}]),
        "POST /api/auth/token/refresh/": () => { renewed = true; return [401, {}]; },
        "GET /api/auth/session/": () => [200, { authenticated: renewed }],
      },
    });
    const r = await client.default.get("/controls/");
    expect(r.data).toEqual({ ok: true });
    expect(window.location.href).toBe("/controls");
  });

  test("WEB-05: in cookie mode a refusal with no session behind it signs out", async () => {
    const { client, window } = await load({
      mode: "cookie",
      routes: {
        "GET /api/controls/": () => [401, {}],
        "POST /api/auth/token/refresh/": () => [401, {}],
        "GET /api/auth/session/": () => [200, { authenticated: false }],
      },
    });
    await expect(client.default.get("/controls/")).rejects.toBeTruthy();
    expect(window.location.href).toBe("/login");
  });
});

test.describe("lists and cold loads", () => {
  const page = (n, more) => [200, { results: [{ id: n }], next: more ? `http://host/api/rows/?page=${n + 1}` : null }];

  test("WEB-10: a list cut short at the page limit says so", async () => {
    const { client } = await load({
      routes: {
        "GET /api/rows/": () => page(1, true),
        "GET /api/rows/?page=2": () => page(2, true),
        "GET /api/rows/?page=3": () => page(3, true),
      },
    });
    const rows = await client.fetchAll("/rows/", 3);
    expect(rows).toHaveLength(3);
    expect(client.isTruncated(rows)).toBe(true);
    // Still an ordinary array for every caller.
    expect(Array.isArray(rows)).toBe(true);
    expect(rows.map((r) => r.id)).toEqual([1, 2, 3]);
  });

  test("WEB-10: a list that ends on the last allowed page is complete", async () => {
    const { client } = await load({
      routes: { "GET /api/rows/": () => page(1, true), "GET /api/rows/?page=2": () => page(2, false) },
    });
    const rows = await client.fetchAll("/rows/", 2);
    expect(client.isTruncated(rows)).toBe(false);
    expect(rows).toHaveLength(2);
  });

  test("AUTH-01: the cold-load renewal asks the endpoint inside the refresh cookie's path, once", async () => {
    const { client, calls } = await load({
      mode: "cookie",
      cookies: "csrftoken=tok",
      routes: { "POST /api/auth/token/renew/": () => [200, { renewed: true }] },
    });
    const [a, b] = await Promise.all([client.renewSession(), client.renewSession()]);
    expect([a, b]).toEqual([true, true]);
    expect(calls).toHaveLength(1);
    expect(calls[0].full.startsWith("POST /api/auth/token/")).toBe(true);
    expect(calls[0].headers["X-CSRFToken"]).toBe("tok");
  });

  test("AUTH-01: an answer of no, or a failure, means sign in", async () => {
    const no = await load({ mode: "cookie", routes: { "POST /api/auth/token/renew/": () => [200, { renewed: false }] } });
    expect(await no.client.renewSession()).toBe(false);
    const down = await load({ mode: "cookie", routes: { "POST /api/auth/token/renew/": dropped } });
    expect(await down.client.renewSession()).toBe(false);
  });
});
