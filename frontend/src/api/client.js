import axios from "axios";

const api = axios.create({ baseURL: "/api" });

// Attach the JWT access token to every request.
api.interceptors.request.use((config) => {
  const token = localStorage.getItem("access");
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

// On a 401, try one silent refresh, then fall back to the login screen.
let refreshing = null;
api.interceptors.response.use(
  (r) => r,
  async (error) => {
    const { response, config } = error;
    if (response?.status === 401 && !config._retry) {
      config._retry = true;
      const refresh = localStorage.getItem("refresh");
      if (refresh) {
        try {
          refreshing =
            refreshing ||
            axios.post("/api/auth/token/refresh/", { refresh });
          const { data } = await refreshing;
          refreshing = null;
          localStorage.setItem("access", data.access);
          config.headers.Authorization = `Bearer ${data.access}`;
          return api(config);
        } catch (e) {
          refreshing = null;
        }
      }
      logout();
      window.location.href = "/login";
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

export function logout() {
  localStorage.removeItem("access");
  localStorage.removeItem("refresh");
}

export function isAuthed() {
  return !!localStorage.getItem("access");
}

export default api;
