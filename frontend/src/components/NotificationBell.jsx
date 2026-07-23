import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import api from "../api/client.js";

// Category → glyph (kept consistent with the sidebar's simple icon set).
const ICON = {
  risk: "△", doc_review: "🗎", event: "◷",
  access_review: "▦", evidence: "❑", meeting: "▤",
};
// Severity → dot colour, reusing the palette's tokens.
const SEV_COLOR = {
  critical: "var(--red)", high: "var(--red)",
  medium: "var(--amber)", low: "var(--accent)", info: "var(--muted)",
};

function BellIcon() {
  return (
    <svg width="19" height="19" viewBox="0 0 24 24" fill="none"
         stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
      <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9" />
      <path d="M13.73 21a2 2 0 0 1-3.46 0" />
    </svg>
  );
}

export default function NotificationBell() {
  const nav = useNavigate();
  const [items, setItems] = useState([]);
  const [unread, setUnread] = useState(0);
  const [open, setOpen] = useState(false);
  const ref = useRef(null);

  async function load() {
    try {
      const { data } = await api.get("/notifications/");
      setItems(data.results);
      setUnread(data.unread);
    } catch {
      /* not signed in yet or transient — leave the bell quiet */
    }
  }

  // Fetch on mount and poll gently so the badge stays roughly live.
  useEffect(() => {
    load();
    const t = setInterval(load, 60000);
    return () => clearInterval(t);
  }, []);

  // Close when clicking outside the panel.
  useEffect(() => {
    function onDoc(e) {
      if (ref.current && !ref.current.contains(e.target)) setOpen(false);
    }
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, []);

  async function toggle() {
    const next = !open;
    setOpen(next);
    // Opening the tray marks everything currently shown as read.
    if (next && unread > 0) {
      setUnread(0);
      setItems((cur) => cur.map((i) => ({ ...i, read: true })));
      try { await api.post("/notifications/mark-read/"); } catch { /* ignore */ }
    }
  }

  async function dismiss(e, key) {
    e.stopPropagation();
    setItems((cur) => cur.filter((i) => i.key !== key));
    try { await api.post("/notifications/dismiss/", { key }); } catch { /* ignore */ }
  }

  function go(item) {
    setOpen(false);
    nav(item.to);
  }

  return (
    <div className="bell-wrap" ref={ref}>
      <button className={"bell-btn" + (open ? " open" : "")} onClick={toggle} aria-label="Notifications">
        <BellIcon />
        {unread > 0 && <span className="bell-badge">{unread > 9 ? "9+" : unread}</span>}
      </button>

      {open && (
        <div className="bell-panel">
          <div className="bell-head">
            <span>Notifications</span>
            <span className="eyebrow">{items.length ? `${items.length} for you` : "nothing right now"}</span>
          </div>
          <div className="bell-list">
            {items.length === 0 ? (
              <div className="bell-empty">You're all caught up.</div>
            ) : (
              items.map((i) => (
                <div key={i.key} className={"bell-item" + (i.read ? "" : " unread")} onClick={() => go(i)}>
                  <span className="bell-dot" style={{ background: SEV_COLOR[i.severity] || "var(--muted)" }} />
                  <span className="bell-cat" aria-hidden="true">{ICON[i.category] || "•"}</span>
                  <div className="bell-meta">
                    <div className="bell-title">{i.title}</div>
                    <div className="bell-detail">{i.detail}</div>
                  </div>
                  <button className="bell-x" title="Dismiss" onClick={(e) => dismiss(e, i.key)}>×</button>
                </div>
              ))
            )}
          </div>
        </div>
      )}
    </div>
  );
}
