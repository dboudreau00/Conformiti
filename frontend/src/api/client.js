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
// The operator sets the password minimum (PASSWORD_MIN_LENGTH). null while
// the server has not reported one, and the getter then answers 12, its default.
let passwordMin = null;

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

/** The shortest password the server accepts. Every screen that sets a
 *  password advertises and checks this one number, so none of them can
 *  promise 12 while the server wants 16, or block an 8 it would take. */
export function passwordMinLength() {
  return passwordMin ?? 12;
}

/** Ask the server which transport is live. Safe to call before signing in.
 *  Also where the CSRF cookie arrives: in cookie mode the login endpoint
 *  checks CSRF, and a visitor who has just opened /login has no token yet,
 *  so this request is the one that seeds it. withCredentials is explicit
 *  rather than relied upon, because the dev server serves the SPA from a
 *  different port than the API. */
export async function loadAuthConfig() {
  try {
    const { data } = await axios.get("/api/auth/config/", { withCredentials: true });
    transport = data.transport === "cookie" ? "cookie" : "header";
    oidc = { enabled: !!data.oidc?.enabled, label: data.oidc?.label || "Single sign-on" };
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
    headers: cookieMode() ? { "X-CSRFToken": csrfToken() } : {},
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

/** Django's CSRF cookie: `__Host-csrftoken` when the site is served over
 *  https (the host-bound prefix), plain `csrftoken` otherwise. */
function csrfToken() {
  return readCookie("__Host-csrftoken") || readCookie("csrftoken") || "";
}

const api = axios.create({ baseURL: "/api", withCredentials: true });

const UNSAFE = ["post", "put", "patch", "delete"];

/** The words shown when a stored file comes back as nginx's job.
 *  With MEDIA_INTERNAL on (the default whenever DJANGO_DEBUG is false) the API
 *  answers a download or a preview with an empty body and an X-Accel-Redirect
 *  header, and nginx replaces it with the file, removing the header. So a
 *  response that still carries the header reached the browser with no nginx
 *  in front: the body is empty, and saving it would give the user a 0-byte
 *  file under the right name with no error anywhere. */
const UNSERVED_FILE_MESSAGE =
  "The server handed this file to a proxy that is not there (an nginx " +
  "X-Accel-Redirect reached the browser), so it arrived empty and was not " +
  "saved. An administrator can fix this by setting MEDIA_INTERNAL=false in " +
  "the server's .env and restarting the backend.";

/** The error to raise for such a response, or null when it is a real one.
 *  It carries the message as response.data.detail as well, the place every
 *  screen's errorText() reads a server refusal from, so each caller that
 *  already reports a failed download shows this sentence instead of its
 *  generic fallback. */
function unservedFileError(response) {
  if (!response?.headers?.["x-accel-redirect"]) return null;
  const error = new Error(UNSERVED_FILE_MESSAGE);
  error.name = "UnservedFileError";
  error.response = { ...response, data: { detail: UNSERVED_FILE_MESSAGE } };
  error.config = response.config;
  return error;
}

// A superuser may work in another organisation's workspace; the choice is
// remembered here and sent on every request. Ignored for everyone else.
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
    // The cookie is attached by the browser; what it cannot forge is this.
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

// A stored file nginx was meant to send (see unservedFileError) fails here,
// for every caller at once: downloadFile, the viewer's preview and its
// SHA-256, which would otherwise hash the empty body and show that.
//
// On a 401, try one silent refresh, then fall back to the login screen.
// Refresh tokens rotate on every use (the server blacklists the old one), so
// the new refresh token from the response must replace the stored one.
let refreshing = null;
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
      const refresh = cookieMode() ? true : localStorage.getItem("refresh");
      if (refresh) {
        try {
          refreshing = refreshing || axios.post(
            "/api/auth/token/refresh/",
            cookieMode() ? {} : { refresh },
            { withCredentials: true,
              headers: cookieMode() ? { "X-CSRFToken": csrfToken() } : {} }
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
  // A different person may be signing in on this browser: drop the previous
  // principal's tokens and workspace choice before the request goes out.
  clearSession();
  const body = withSecondFactor({ username, password }, second);
  const { data } = await axios.post("/api/auth/token/", body, {
    withCredentials: true,
    headers: cookieMode() ? { "X-CSRFToken": csrfToken() } : {},
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
  chooseWorkspace("");
}

/** Revoke server-side, then clear local state. Always resolves, a failed
 * revoke must never trap the user in a signed-in shell.
 *
 * Cookie mode goes through /auth/token/clear/ rather than /auth/logout/:
 * the SPA cannot clear an HttpOnly cookie itself, and logout requires
 * authentication, so a sign-out after the access cookie expired would 401 and
 * leave a live 7-day refresh cookie behind a UI that said "signed out".
 *
 * The refresh cookie's path is /api/auth/token/, so only an endpoint under
 * that path receives it. /auth/session/clear/ does not, which meant a
 * sign-out with an expired access cookie cleared the browser but never
 * revoked the token. It stays as the fallback for a server older than 0.9.5b.
 */
export async function logout() {
  try {
    if (cookieMode()) {
      try {
        await api.post("/auth/token/clear/", {});
      } catch (err) {
        if (err?.response?.status !== 404) throw err;
        await api.post("/auth/session/clear/", {});
      }
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

/** The file name a Content-Disposition header carries, or "" if none.
 *  filename* (RFC 5987: the exact UTF-8 name, non-ASCII included) wins over
 *  the plain filename=, which is only the server's ASCII fallback. */
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

/** Trigger a browser download of a blob response (CSV exports, documents).
 *  The name is the one the server sent in Content-Disposition, so a document
 *  saves as "Access Control Policy.pdf" exactly as a direct download would;
 *  `filename` is used only when the response names nothing.
 *
 *  Rejects, saving nothing, when the server handed the file to an nginx that
 *  is not there: the api instance turns an X-Accel-Redirect that reached the
 *  browser into an error naming MEDIA_INTERNAL=false (unservedFileError), so
 *  the empty body never becomes a 0-byte file. Callers report the rejection
 *  the way they report any failed download.
 *
 *  A refusal's JSON body arrives as a Blob under responseType "blob", where
 *  errorText cannot read its detail (a quarantined document would read as a
 *  bare "no permission"), so it is parsed back into an object first. */
export async function downloadFile(url, filename) {
  let r;
  try {
    r = await api.get(url, { responseType: "blob" });
  } catch (e) {
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
  // Revoking in the same tick can cancel the download before the browser
  // has read the blob (Firefox does), so give it a moment.
  setTimeout(() => URL.revokeObjectURL(href), 1500);
}

export default api;
