import axios from "axios";

const api = axios.create({ baseURL: "/api" });

// Attach the JWT access token to every request.
api.interceptors.request.use((config) => {
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
      const refresh = localStorage.getItem("refresh");
      if (refresh) {
        try {
          refreshing = refreshing || axios.post("/api/auth/token/refresh/", { refresh });
          const { data } = await refreshing;
          refreshing = null;
          localStorage.setItem("access", data.access);
          if (data.refresh) localStorage.setItem("refresh", data.refresh);
          config.headers.Authorization = `Bearer ${data.access}`;
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

export async function login(username, password, otp) {
  const body = { username, password };
  if (otp) body.otp = otp;
  const { data } = await axios.post("/api/auth/token/", body);
  localStorage.setItem("access", data.access);
  localStorage.setItem("refresh", data.refresh);
  return data;
}

function clearSession() {
  localStorage.removeItem("access");
  localStorage.removeItem("refresh");
}

/** Revoke the refresh token server-side, then clear local state. Always
 * resolves — a failed revoke must never trap the user in a signed-in shell. */
export async function logout() {
  const refresh = localStorage.getItem("refresh");
  try {
    if (refresh) await api.post("/auth/logout/", { refresh });
  } catch {
    /* already expired or offline */
  }
  clearSession();
}

export function isAuthed() {
  return !!localStorage.getItem("access");
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
