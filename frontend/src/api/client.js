import axios from "axios";

// The server decides how credentials travel; the SPA asks once at boot.
//
//   "header"  tokens live in localStorage and go out as Authorization
//             (the default, and what every 0.2.x deployment runs);
//   "cookie"  the server sets HttpOnly cookies script cannot read, and unsafe
//             methods must echo Django's CSRF token.
//
// withCredentials is on in both modes: harmless for header auth, required for
// cookie auth, and one less thing to get wrong when the server flips.
let transport = "header";
let oidc = { enabled: false, label: "" };
let saml = { enabled: false, label: "" };

export function authTransport() {
  return transport;
}

export function cookieMode() {
  return transport === "cookie";
}

/** Whether the server offers single sign-on, and what to call the button. */
export function oidcConfig() {
  return oidc;
}

export function samlConfig() {
  return saml;
}

/** Ask the server which transport is live. Safe to call before signing in. */
export async function loadAuthConfig() {
  try {
    const { data } = await axios.get("/api/auth/config/");
    transport = data.transport === "cookie" ? "cookie" : "header";
    oidc = { enabled: !!data.oidc?.enabled, label: data.oidc?.label || "Single sign-on" };
    saml = { enabled: !!data.saml?.enabled, label: data.saml?.label || "Sign in with SAML" };
  } catch {
    transport = "header";
    oidc = { enabled: false, label: "" };
    saml = { enabled: false, label: "" };
  }
  return transport;
}

/** The second factor a sign-in call carries: {otp} for an authenticator or
 *  backup code, {passkey: {state, credential}} for a WebAuthn assertion. */
function withSecondFactor(body, second) {
  if (typeof second === "string") second = { otp: second };
  if (second?.otp) body.otp = second.otp;
  if (second?.passkey) body.passkey = second.passkey;
  return body;
}

/** Finish a single sign-on: swap the one-time ticket from the callback
 *  redirect for tokens, delivered the same way a password login delivers them.
 *  When the server wants a local second factor first it answers
 *  {mfa_required: true, factors, passkey?} and keeps the ticket; call again
 *  with the code or the passkey assertion. */
export async function redeemSso(ticket, second) {
  const body = withSecondFactor({ ticket }, second);
  const { data } = await axios.post("/api/auth/oidc/redeem/", body, {
    withCredentials: true,
    headers: cookieMode() ? { "X-CSRFToken": readCookie("csrftoken") || "" } : {},
  });
  if (data?.mfa_required) return data;
  if (!cookieMode()) {
    localStorage.setItem("access", data.access);
    localStorage.setItem("refresh", data.refresh);
  }
  return data;
}

function readCookie(name) {
  const match = document.cookie.match(new RegExp(`(?:^|; )${name}=([^;]*)`));
  return match ? decodeURIComponent(match[1]) : null;
}

const api = axios.create({ baseURL: "/api", withCredentials: true });

const UNSAFE = ["post", "put", "patch", "delete"];

api.interceptors.request.use((config) => {
  if (cookieMode()) {
    // The cookie is attached by the browser; what it cannot forge is this.
    if (UNSAFE.includes((config.method || "get").toLowerCase())) {
      const csrf = readCookie("csrftoken");
      if (csrf) config.headers["X-CSRFToken"] = csrf;
    }
    return config;
  }
  const token = localStorage.getItem("access");
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

// On a 401, try one silent refresh, then fall back to the login screen.
// Refresh tokens rotate on every use (the server blacklists the old one), so
// the new refresh token from the response must replace the stored one.
let refreshing = null;
api.interceptors.response.use(
  (r) => r,
  async (error) => {
    const { response, config } = error;
    if (response?.status === 401 && config && !config._retry && !config.url?.includes("/auth/")) {
      config._retry = true;
      const refresh = cookieMode() ? true : localStorage.getItem("refresh");
      if (refresh) {
        try {
          refreshing = refreshing || axios.post(
            "/api/auth/token/refresh/",
            cookieMode() ? {} : { refresh },
            { withCredentials: true,
              headers: cookieMode() ? { "X-CSRFToken": readCookie("csrftoken") || "" } : {} }
          );
          const { data } = await refreshing;
          refreshing = null;
          if (!cookieMode()) {
            localStorage.setItem("access", data.access);
            if (data.refresh) localStorage.setItem("refresh", data.refresh);
            config.headers.Authorization = `Bearer ${data.access}`;
          }
          return api(config);
        } catch (e) {
          refreshing = null;
        }
      }
      clearSession();
      if (window.location.pathname !== "/login") window.location.href = "/login";
    }
    return Promise.reject(error);
  }
);

export async function login(username, password, second) {
  const body = withSecondFactor({ username, password }, second);
  const { data } = await axios.post("/api/auth/token/", body, {
    withCredentials: true,
    headers: cookieMode() ? { "X-CSRFToken": readCookie("csrftoken") || "" } : {},
  });
  if (!cookieMode()) {
    localStorage.setItem("access", data.access);
    localStorage.setItem("refresh", data.refresh);
  }
  return data;
}

function clearSession() {
  localStorage.removeItem("access");
  localStorage.removeItem("refresh");
}

/** Revoke server-side, then clear local state. Always resolves — a failed
 * revoke must never trap the user in a signed-in shell.
 *
 * Cookie mode goes through /auth/session/clear/ rather than /auth/logout/:
 * the SPA cannot clear an HttpOnly cookie itself, and logout requires
 * authentication, so a sign-out after the access cookie expired would 401 and
 * leave a live 7-day refresh cookie behind a UI that said "signed out".
 */
export async function logout() {
  try {
    if (cookieMode()) {
      await api.post("/auth/session/clear/", {});
    } else {
      const refresh = localStorage.getItem("refresh");
      if (refresh) await api.post("/auth/logout/", { refresh });
    }
  } catch {
    /* already expired, or offline */
  }
  clearSession();
}

/** Synchronous best guess, used only to decide whether to render the shell
 *  while the real answer is in flight. In cookie mode the only authority is
 *  the server, so ask it with `session()`. */
export function isAuthed() {
  return cookieMode() ? true : !!localStorage.getItem("access");
}

/** The server's answer: {transport, authenticated, renewable, username}. */
export async function session() {
  const { data } = await api.get("/auth/session/");
  return data;
}

/** Follow DRF pagination `next` links until every row is collected. */
export async function fetchAll(url, maxPages = 50) {
  const all = [];
  let next = url;
  for (let guard = 0; next && guard < maxPages; guard++) {
    const r = await api.get(next);
    const page = r.data.results || r.data;
    all.push(...page);
    next = r.data.next ? r.data.next.replace(/^.*\/api/, "") : null;
  }
  return all;
}

/** Trigger a browser download of a blob response (CSV exports). */
export async function downloadFile(url, filename) {
  const r = await api.get(url, { responseType: "blob" });
  const href = URL.createObjectURL(r.data);
  const a = document.createElement("a");
  a.href = href;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(href);
}

export default api;
