import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import { BellIcon, XIcon } from "lucide-react";
import api from "../api/client.js";
import { cn } from "../utils/cn.js";
import { TONE_FILL } from "../utils/tone.js";
import { Label } from "./ui/Panel.jsx";
import { Popover } from "./ui/Popover.jsx";

const SEV_TONE = { critical: "danger", high: "danger", medium: "warning", low: "info", info: "muted" };

export default function NotificationBell() {
  const nav = useNavigate();
  const [items, setItems] = useState([]);
  const [unread, setUnread] = useState(0);
  const [open, setOpen] = useState(false);

  async function load() {
    try {
      const { data } = await api.get("/notifications/");
      setItems(data.results);
      setUnread(data.unread);
    } catch {
      /* not signed in yet or transient, leave the bell quiet */
    }
  }

  // Fetch on mount and poll gently so the badge stays roughly live.
  useEffect(() => {
    load();
    const t = setInterval(load, 60000);
    return () => clearInterval(t);
  }, []);

  // Opening the tray marks everything currently shown as read.
  async function onOpenChange(next) {
    setOpen(next);
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
    <Popover
      open={open}
      onOpenChange={onOpenChange}
      label="Notifications"
      role="group"
      panelClassName="sm:w-[340px]"
      trigger={(p) => (
        <button
          type="button"
          {...p}
          aria-label={`Notifications, ${unread} unread`}
          className={cn(
            "relative flex h-[34px] w-[34px] items-center justify-center rounded-lg border border-line bg-surface text-muted",
            "transition-colors duration-150 ease-out hover:border-line-strong hover:bg-surface-2 hover:text-ink",
            open && "border-line-strong bg-surface-2 text-ink"
          )}
        >
          <BellIcon className="h-4 w-4" strokeWidth={1.75} aria-hidden="true" />
          {unread > 0 ? (
            <span className="tabular absolute -right-1.5 -top-1.5 flex h-4 min-w-[16px] items-center justify-center rounded-full bg-danger px-1 font-mono text-[9px] font-medium text-white">
              {unread > 9 ? "9+" : unread}
            </span>
          ) : null}
        </button>
      )}
    >
      <div className="flex items-center justify-between border-b border-line px-3 py-2">
        <Label>Activity</Label>
        <Label>{items.length ? `${items.length} for you` : "nothing right now"}</Label>
      </div>
      <ul className="max-h-[420px] divide-y divide-line overflow-y-auto">
        {items.length === 0 ? (
          <li className="px-3 py-8 text-center text-xs text-muted">You're all caught up.</li>
        ) : (
          items.map((i, idx) => (
            <motion.li
              key={i.key}
              initial={{ opacity: 0, x: 6 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ duration: 0.18, ease: [0.23, 1, 0.32, 1], delay: 0.03 * idx }}
              className={cn("flex items-start gap-2.5 px-3 py-2.5", !i.read && "bg-accent/[0.05]")}
            >
              <span className={cn("mt-1.5 h-2 w-2 shrink-0 rounded-full", TONE_FILL[SEV_TONE[i.severity] || "muted"])} aria-hidden="true" />
              <button type="button" onClick={() => go(i)} className="min-w-0 flex-1 text-left">
                <span className={cn("block text-[13px] leading-snug", SEV_TONE[i.severity] === "danger" ? "text-danger" : "text-ink")}>{i.title}</span>
                <Label className="mt-1 block truncate">{i.detail}</Label>
              </button>
              <button
                type="button"
                onClick={(e) => dismiss(e, i.key)}
                aria-label="Dismiss"
                className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-faint opacity-60 transition-opacity hover:bg-surface-2 hover:text-ink hover:opacity-100 focus-visible:opacity-100"
              >
                <XIcon className="h-3.5 w-3.5" strokeWidth={2} />
              </button>
            </motion.li>
          ))
        )}
      </ul>
    </Popover>
  );
}
