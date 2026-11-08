/** For elements that must stay non-buttons (table rows, tree nodes): Enter and Space fire `fn` like a click. */
export function onActivate(fn) {
  return (e) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      fn(e);
    }
  };
}

/** "" keeps LoadError's default sentence, which is only true when no response arrived. A 5xx answers with a status
 * line, never the body, so a raw HTML error page cannot reach the screen. */
export function loadFailReason(e) {
  const r = e?.response;
  if (!r) return "";
  if (r.status < 500 && r.data && typeof r.data === "object") return errorText(e);
  if (r.status === 403) return "You don't have permission to see this.";
  return SERVER_FAULT;
}

const NO_ANSWER = "The server did not answer. Check your connection and try again.";
const SERVER_FAULT = "The server had a problem. Try again in a moment.";
const TOO_OFTEN = "That was asked too often. Wait a minute and try again.";

/** Words for the field keys a server error names; a key with no entry is spelled out from its own letters. */
function fieldLabel(key, names) {
  if (names?.[key]) return names[key];
  const words = String(key).replace(/_/g, " ").trim();
  return `${words.charAt(0).toUpperCase()}${words.slice(1)}`;
}

/** What a person reads after a failed call. Never a raw body (HTML, a throttle line), a status number, or an
 * unnamed field key; `names` maps the keys a form shows to the labels it shows. */
const GENERIC = "Something went wrong. Please try again.";

export function errorText(e, fallback = GENERIC, names) {
  const r = e?.response;
  // A caller that names what it was doing ("Couldn't export the request list.") keeps its own sentence when the server
  // only says it failed; the stock sentences below are for the callers that passed none.
  const own = fallback !== GENERIC;
  if (!r) return e?.isAxiosError ? (own ? fallback : NO_ANSWER) : fallback;
  const d = r.data;
  if (r.status === 429) return TOO_OFTEN;
  if (typeof d === "string" && d.trim() && !d.trim().startsWith("<")) return r.status >= 500 ? (own ? fallback : SERVER_FAULT) : d;
  if (d?.detail) return String(d.detail);
  if (d && typeof d === "object" && !Array.isArray(d)) {
    const first = Object.entries(d).find(([k]) => k !== "code");
    if (first) {
      const [k, v] = first;
      const msg = Array.isArray(v) ? v.join(" ") : String(v);
      return k === "non_field_errors" ? msg : `${fieldLabel(k, names)}: ${msg}`;
    }
  }
  if (r.status === 413) return "That file is too large to upload.";
  if (r.status === 403) return "You don't have permission to do that.";
  if (r.status === 404) return "That no longer exists. Reload the page and try again.";
  if (r.status >= 500) return own ? fallback : SERVER_FAULT;
  return fallback;
}
