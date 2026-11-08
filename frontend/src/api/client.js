import axios from "axios";

// "header": tokens in localStorage, sent as Authorization. "cookie": HttpOnly cookies, and unsafe methods echo the
// CSRF token. The server picks the mode; withCredentials stays on in both because cookie mode needs it.
let transport = "header";
let oidc = { enabled: false, label: "" };
let saml = { enabled: false, label: "" };
let passwordMin = null;

export function authTransport() {
  return transport;
}

export function cookieMode() {
  return transport === "cookie";
}

export function oidcConfig() {
  return oidc;
}

export function samlConfig() {
  return saml;
}

/** Operator-set (PASSWORD_MIN_LENGTH): every screen that sets a password must use this, never a literal. */
export function passwordMinLength() {
  return passwordMin ?? 12;
}

/** Also seeds the CSRF cookie that cookie-mode login checks, so it must run before sign-in. withCredentials is
 * explicit because the dev server serves the SPA from a different port than the API. */
export async function loadAuthConfig() {
  try {
    const { data } = await axios.get("/api/auth/config/", { withCredentials: true });
    transport = data.transport === "cookie" ? "cookie" : "header";
    oidc = { enabled: !!data.oidc?.enabled, label: data.oidc?.label || "Sign in with SSO" };
    saml = { enabled: !!data.saml?.enabled, label: data.saml?.label || "Sign in with SAML" };
    const min = data.password_min_length;
    passwordMin = Number.isInteger(min) && min > 0 ? min : null;
  } catch {
    transport = "header";
    oidc = { enabled: false, label: "" };
    saml = { enabled: false, label: "" };
    passwordMin = null;
  }
  return transport;
}

/** `second` is an OTP or backup-code string, {otp}, or {passkey: {state, credential}} for a WebAuthn assertion. */
function withSecondFactor(body, second) {
  if (typeof second === "string") second = { otp: second };
  if (second?.otp) body.otp = second.otp;
  if (second?.passkey) body.passkey = second.passkey;
  return body;
}

/** Resolves {mfa_required: true, factors, passkey?} while a local second factor is owed (the ticket stays valid);
 * call again with `second`. */
export async function redeemSso(ticket, second) {
  const body = withSecondFactor({ ticket }, second);
  const { data } = await axios.post("/api/auth/oidc/redeem/", body, {
    withCredentials: true,
    headers: cookieMode() ? { "X-CSRFToken": csrfToken() } : {},
  });
  if (data?.mfa_required) return data;
  startSession(data);
  return data;
}

/** A new principal has been accepted by the server: only now drop the previous one's workspace choice and tokens,
 * so a refused attempt (a wrong password, a second factor still owed) leaves another tab's session alone. */
function startSession(data) {
  const previous = cookieMode() ? null : localStorage.getItem("refresh");
  clearSession();
  if (cookieMode()) return;
  localStorage.setItem("access", data.access);
  localStorage.setItem("refresh", data.refresh);
  // Nobody holds the replaced refresh token any more: revoke it rather than leave it live for its 7 days.
  if (previous && previous !== data.refresh) revokeQuietly(previous);
}

function revokeQuietly(refresh) {
  // No Authorization header: the access token that went with it may be gone, and a dead one is refused before the view.
  axios.post("/api/auth/token/clear/", { refresh }, { withCredentials: true }).catch(() => {});
}

function readCookie(name) {
  const match = document.cookie.match(new RegExp(`(?:^|; )${name}=([^;]*)`));
  return match ? decodeURIComponent(match[1]) : null;
}

function csrfToken() {
  return readCookie("__Host-csrftoken") || readCookie("csrftoken") || "";
}

const api = axios.create({ baseURL: "/api", withCredentials: true });

const UNSAFE = ["post", "put", "patch", "delete"];

const UNSERVED_FILE_MESSAGE = "The file could not be downloaded. Ask your administrator to check the file server settings.";

// For whoever runs the server: the console, never the page.
const UNSERVED_FILE_DETAIL =
  "The server handed this file to a proxy that is not there (an nginx X-Accel-Redirect reached the browser), so it " +
  "arrived empty and was not saved. Set MEDIA_INTERNAL=false in the server's .env and restart the backend.";

// An X-Accel-Redirect header that reaches the browser means no nginx swapped in the file: the empty body must never
// be saved or hashed. Thrown from the interceptor for every caller; also set as response.data.detail for errorText().
function unservedFileError(response) {
  if (!response?.headers?.["x-accel-redirect"]) return null;
  console.warn(UNSERVED_FILE_DETAIL);
  const error = new Error(UNSERVED_FILE_MESSAGE);
  error.name = "UnservedFileError";
  error.response = { ...response, data: { detail: UNSERVED_FILE_MESSAGE } };
  error.config = response.config;
  return error;
}

// Superuser-only: the chosen slug goes out as X-Workspace on every request; the server ignores it for everyone else.
export function chosenWorkspace() {
  try { return localStorage.getItem("workspace") || ""; } catch { return ""; }
}
export function chooseWorkspace(slug) {
  try { slug ? localStorage.setItem("workspace", slug) : localStorage.removeItem("workspace"); } catch { /* private mode */ }
}

api.interceptors.request.use((config) => {
  const workspace = chosenWorkspace();
  if (workspace) config.headers["X-Workspace"] = workspace;
  if (cookieMode()) {
    // CSRF double-submit: the browser sends the cookie by itself, so the echoed header is the proof.
    if (UNSAFE.includes((config.method || "get").toLowerCase())) {
      const csrf = csrfToken();
      if (csrf) config.headers["X-CSRFToken"] = csrf;
    }
    return config;
  }
  const token = localStorage.getItem("access");
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

// On a 401: one silent refresh, then the login screen. Refresh tokens rotate (the old one is blacklisted), so the
// refresh token in the response must replace the stored one.
let refreshing = null;

// "renewed", "refused" (the server rejected the token: 400, 401 or 403) or "unreachable" (no answer, a 5xx, a throttle).
async function renewTokens() {
  refreshing = refreshing || axios.post(
    "/api/auth/token/refresh/",
    cookieMode() ? {} : { refresh: localStorage.getItem("refresh") },
    { withCredentials: true,
      headers: cookieMode() ? { "X-CSRFToken": csrfToken() } : {} }
  );
  const attempt = refreshing;
  try {
    const { data } = await attempt;
    if (!cookieMode()) {
      localStorage.setItem("access", data.access);
      if (data.refresh) localStorage.setItem("refresh", data.refresh);
    }
    return "renewed";
  } catch (ex) {
    const status = ex?.response?.status;
    return status === 400 || status === 401 || status === 403 ? "refused" : "unreachable";
  } finally {
    // Only the setter clears it: a later refresh must not be wiped by an earlier waiter.
    if (refreshing === attempt) refreshing = null;
  }
}

// Another tab may have won the race to rotate the token this one sent: the browser then already holds the new one.
async function renewedElsewhere(sent) {
  if (cookieMode()) {
    try {
      return !!(await session()).authenticated;
    } catch {
      return false;
    }
  }
  const stored = localStorage.getItem("refresh");
  return !!stored && stored !== sent && !!localStorage.getItem("access");
}

api.interceptors.response.use(
  (r) => {
    const unserved = unservedFileError(r);
    if (unserved) throw unserved;
    return r;
  },
  async (error) => {
    const { response, config } = error;
    if (response?.status === 401 && config && !config._retry && !config.url?.includes("/auth/")) {
      config._retry = true;
      const sent = cookieMode() ? true : localStorage.getItem("refresh");
      if (sent) {
        const outcome = await renewTokens();
        // Not a verdict on the session: a dropped connection or a busy server must not sign the person out.
        if (outcome === "unreachable") return Promise.reject(error);
        if (outcome === "renewed" || await renewedElsewhere(sent)) {
          if (!cookieMode()) config.headers.Authorization = `Bearer ${localStorage.getItem("access")}`;
          return api(config);
        }
      }
      // Tokens only: the workspace choice goes with an explicit sign-out or a new principal (startSession).
      clearTokens();
      if (window.location.pathname !== "/login") window.location.href = "/login";
    }
    return Promise.reject(error);
  }
);

export async function login(username, password, second) {
  const body = withSecondFactor({ username, password }, second);
  const { data } = await axios.post("/api/auth/token/", body, {
    withCredentials: true,
    headers: cookieMode() ? { "X-CSRFToken": csrfToken() } : {},
  });
  // Another person may be signing in, but only an accepted sign-in replaces the previous principal.
  startSession(data);
  return data;
}

function clearTokens() {
  localStorage.removeItem("access");
  localStorage.removeItem("refresh");
}

function clearSession() {
  clearTokens();
  chooseWorkspace("");
}

/** Always resolves: a failed revoke must not trap the user in a signed-in shell. Cookie mode uses /auth/token/clear/,
 * not /auth/logout/, which needs auth and would 401 with the access cookie expired, leaving the refresh cookie live. */
export async function logout() {
  try {
    if (cookieMode()) {
      try {
        await api.post("/auth/token/clear/", {});
      } catch (err) {
        // Older servers lack token/clear/; session/clear/ only clears the browser and cannot revoke the token.
        if (err?.response?.status !== 404) throw err;
        await api.post("/auth/session/clear/", {});
      }
    } else {
      const refresh = localStorage.getItem("refresh");
      if (refresh) {
        try {
          await api.post("/auth/logout/", { refresh });
        } catch (err) {
          // The access token has expired, so the authenticated route refused before it read the body. The refresh
          // token must still be revoked: send it alone to the route that needs no access token.
          if (err?.response?.status !== 401) throw err;
          await axios.post("/api/auth/token/clear/", { refresh }, { withCredentials: true });
        }
      }
    }
  } catch {
    /* already expired, or offline */
  }
  clearSession();
}

/** A synchronous guess for rendering the shell only; in cookie mode the authority is session(). */
export function isAuthed() {
  return cookieMode() ? true : !!localStorage.getItem("access");
}

export async function session() {
  const { data } = await api.get("/auth/session/");
  return data;
}

let renewing = null;

/** Cookie mode, cold load: the access cookie has lapsed but the 7-day refresh cookie may not have. The probe above
 * cannot see that cookie (its path is narrower), so this asks the one endpoint it travels to. Resolves true once the
 * session is renewed, false for "sign in"; never rejects. One request at a time, so a double mount shares it. */
export function renewSession() {
  renewing = renewing || axios.post("/api/auth/token/renew/", {}, {
    withCredentials: true,
    headers: { "X-CSRFToken": csrfToken() },
  }).then(({ data }) => !!data?.renewed, () => false).finally(() => { renewing = null; });
  return renewing;
}

/** Every page of a list. When `maxPages` ran out first the array carries `truncated: true` (see isTruncated), so a
 * screen can say the list is incomplete instead of presenting it as everything. */
export async function fetchAll(url, maxPages = 50) {
  const all = [];
  let next = url;
  for (let guard = 0; next && guard < maxPages; guard++) {
    const r = await api.get(next);
    const page = r.data.results || r.data;
    all.push(...page);
    next = r.data.next ? r.data.next.replace(/^.*\/api/, "") : null;
  }
  if (next) all.truncated = true;
  return all;
}

/** True when fetchAll stopped before the last page. A copy made with filter, map or spread loses the flag: ask the
 * array fetchAll returned. */
export function isTruncated(rows) {
  return !!rows?.truncated;
}

// filename* (RFC 5987, the exact UTF-8 name) wins over the plain filename=, the server's ASCII fallback.
function dispositionFilename(header) {
  const value = String(header || "");
  const star = /filename\*\s*=\s*([\w-]*)'[^']*'([^;]+)/i.exec(value);
  if (star && /^utf-8$/i.test(star[1])) {
    try {
      const name = decodeURIComponent(star[2].trim());
      if (name) return name;
    } catch { /* a malformed escape: use filename= below */ }
  }
  const plain = /(?:^|;)\s*filename\s*=\s*(?:"([^"]*)"|([^;]*))/i.exec(value);
  return plain ? (plain[1] ?? plain[2] ?? "").trim() : "";
}

/** Saves under the server's Content-Disposition name; `filename` is only the fallback. Rejects, saving nothing, when
 * the file was never served (see unservedFileError). */
export async function downloadFile(url, filename) {
  let r;
  try {
    r = await api.get(url, { responseType: "blob" });
  } catch (e) {
    // A refusal's JSON arrives as a Blob under responseType "blob"; parse it back so errorText can read the detail.
    const data = e?.response?.data;
    if (typeof Blob !== "undefined" && data instanceof Blob) {
      try {
        e.response.data = JSON.parse(await data.text());
      } catch { /* not JSON: leave the body as it came */ }
    }
    throw e;
  }
  const href = URL.createObjectURL(r.data);
  const a = document.createElement("a");
  a.href = href;
  a.download = dispositionFilename(r.headers?.["content-disposition"]) || filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  // Revoking in the same tick can cancel the download in Firefox.
  setTimeout(() => URL.revokeObjectURL(href), 1500);
}

export default api;
