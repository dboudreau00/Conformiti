/** Keyboard activation for non-button elements that must stay non-buttons
 * (table rows, tree nodes). Enter/Space trigger the handler like a click. */
export function onActivate(fn) {
  return (e) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      fn(e);
    }
  };
}

/** What a LoadError should say about a failed load, or "" to keep its default.
 *
 * LoadError's own sentence ("The request did not come back") is only true when
 * no response arrived. A server that answered with a
 * refusal or an error deserves its own words, and a raw HTML error page never
 * reaches the screen. */
export function loadFailReason(e) {
  const r = e?.response;
  if (!r) return "";
  if (r.status < 500 && r.data && typeof r.data === "object") return errorText(e);
  if (r.status === 403) return "You don't have permission to see this.";
  return `The server returned an error (${r.status}). Try again.`;
}

/** Extract a human-readable message from a failed axios call. */
export function errorText(e, fallback = "Something went wrong. Please try again.") {
  const d = e?.response?.data;
  if (typeof d === "string" && d) return d;
  if (d?.detail) return String(d.detail);
  if (d && typeof d === "object") {
    const first = Object.entries(d)[0];
    if (first) {
      const [k, v] = first;
      const msg = Array.isArray(v) ? v.join(" ") : String(v);
      // The field's name in words ("Base url"), not the API's key ("base_url").
      const field = k.replace(/_/g, " ");
      return k === "non_field_errors" ? msg : `${field.charAt(0).toUpperCase()}${field.slice(1)}: ${msg}`;
    }
  }
  if (e?.response?.status === 413) return "That file is too large to upload.";
  if (e?.response?.status === 403) return "You don't have permission to do that.";
  return fallback;
}
