import { useEffect, useState } from "react";
import api from "../api/client.js";
import { THEMES, ACCENT_PRESETS, getTheme, getAccent, setTheme, setAccent } from "../theme.js";

const SECTIONS = [
  { key: "profile", label: "Profile", icon: "◉" },
  { key: "security", label: "Security", icon: "⚿" },
  { key: "notifications", label: "Notifications", icon: "✉" },
  { key: "appearance", label: "Appearance", icon: "◑" },
  { key: "access", label: "Role & access", icon: "▤" },
  { key: "about", label: "About", icon: "ⓘ" },
];

const CAP_LABELS = {
  manage_users: "Manage users & roles",
  manage_frameworks: "Manage frameworks & controls",
  manage_documents: "Manage document library",
  manage_folders: "Manage folders & permissions",
  view_all: "View all folders (bypass restrictions)",
  auditor: "Auditor (read-only)",
};

function Profile({ me, onUpdate }) {
  const [form, setForm] = useState({
    first_name: me?.first_name || "",
    last_name: me?.last_name || "",
    email: me?.email || "",
    job_title: me?.job_title || "",
  });
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState(null);

  // `me` loads asynchronously; if the user lands directly on /account the form
  // mounts before the profile arrives, so sync the fields when it does.
  useEffect(() => {
    setForm({
      first_name: me?.first_name || "",
      last_name: me?.last_name || "",
      email: me?.email || "",
      job_title: me?.job_title || "",
    });
  }, [me?.id]);

  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });

  async function save() {
    setSaving(true); setMsg(null);
    try {
      const { data } = await api.patch("/users/me/", form);
      onUpdate?.(data);
      setMsg({ ok: true, text: "Profile saved." });
    } catch (e) {
      setMsg({ ok: false, text: "Couldn't save. Check the fields and try again." });
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="acct-panel">
      <h2>Profile</h2>
      <p className="acct-sub">How you appear across the workspace and on documents you own.</p>
      <div className="acct-grid2">
        <div className="field"><label>First name</label><input value={form.first_name} onChange={set("first_name")} /></div>
        <div className="field"><label>Last name</label><input value={form.last_name} onChange={set("last_name")} /></div>
      </div>
      <div className="field"><label>Email</label><input type="email" value={form.email} onChange={set("email")} /></div>
      <div className="field"><label>Job title</label><input value={form.job_title} onChange={set("job_title")} placeholder="e.g. Security Analyst" /></div>
      <div className="field"><label>Username</label><input value={me?.username || ""} disabled /><div className="hint">Usernames are managed by an administrator.</div></div>
      {msg && <div className={msg.ok ? "notice ok" : "error"}>{msg.text}</div>}
      <button className="btn primary" onClick={save} disabled={saving}>{saving ? "Saving…" : "Save changes"}</button>
    </div>
  );
}

function BackupCodes({ codes }) {
  function download() {
    const text =
      "Conformiti — backup codes\n" +
      "Each code works once. Keep them somewhere safe.\n\n" + codes.join("\n") + "\n";
    const url = URL.createObjectURL(new Blob([text], { type: "text/plain" }));
    const a = document.createElement("a");
    a.href = url; a.download = "compliance-backup-codes.txt"; a.click();
    URL.revokeObjectURL(url);
  }
  return (
    <div className="notice ok" style={{ marginTop: 12 }}>
      <div style={{ fontWeight: 600, marginBottom: 6 }}>Save your backup codes</div>
      <div style={{ fontSize: 12.5, marginBottom: 10 }}>
        Each code can be used once if you lose your authenticator. They won't be shown again.
      </div>
      <div className="backup-grid">
        {codes.map((c) => <span key={c} className="mono">{c}</span>)}
      </div>
      <button className="btn small" style={{ marginTop: 10 }} onClick={download}>Download .txt</button>
    </div>
  );
}

function Mfa() {
  const [status, setStatus] = useState(null);      // {enabled, pending, backup_codes_remaining}
  const [setup, setSetup] = useState(null);        // {secret, otpauth_uri}
  const [code, setCode] = useState("");
  const [password, setPassword] = useState("");
  const [codes, setCodes] = useState(null);        // freshly issued backup codes
  const [msg, setMsg] = useState(null);
  const [busy, setBusy] = useState(false);

  function loadStatus() {
    api.get("/auth/mfa/status/").then((r) => setStatus(r.data)).catch(() => setStatus({ enabled: false }));
  }
  useEffect(() => { loadStatus(); }, []);

  async function begin() {
    setMsg(null); setCodes(null); setBusy(true);
    try {
      const { data } = await api.post("/auth/mfa/setup/");
      setSetup(data);
    } catch (e) {
      setMsg({ ok: false, text: e?.response?.data?.detail || "Couldn't start setup." });
    } finally { setBusy(false); }
  }

  async function confirm() {
    setMsg(null); setBusy(true);
    try {
      const { data } = await api.post("/auth/mfa/verify/", { code });
      setCodes(data.backup_codes);
      setSetup(null); setCode("");
      loadStatus();
      setMsg({ ok: true, text: "Two-factor authentication is on." });
    } catch (e) {
      setMsg({ ok: false, text: e?.response?.data?.detail || "That code isn't valid." });
    } finally { setBusy(false); }
  }

  async function disable() {
    setMsg(null); setBusy(true);
    try {
      await api.post("/auth/mfa/disable/", { password });
      setPassword(""); setCodes(null);
      loadStatus();
      setMsg({ ok: true, text: "Two-factor authentication is off." });
    } catch (e) {
      setMsg({ ok: false, text: e?.response?.data?.detail || "Couldn't disable MFA." });
    } finally { setBusy(false); }
  }

  async function regen() {
    setMsg(null); setBusy(true);
    try {
      const { data } = await api.post("/auth/mfa/backup-codes/", { password });
      setCodes(data.backup_codes); setPassword("");
      loadStatus();
    } catch (e) {
      setMsg({ ok: false, text: e?.response?.data?.detail || "Couldn't regenerate codes." });
    } finally { setBusy(false); }
  }

  const secretGrouped = setup?.secret ? setup.secret.replace(/(.{4})/g, "$1 ").trim() : "";

  return (
    <div className="acct-panel" style={{ marginTop: 26 }}>
      <h2>Two-factor authentication</h2>
      <p className="acct-sub">
        Add a one-time code from an authenticator app (Google Authenticator, Authy,
        1Password, Microsoft Authenticator) to your sign-in.
      </p>

      {status && (
        <div className="info-row">
          <span className="info-k">Status</span>
          <span className="info-v">
            {status.enabled
              ? <span className="badge ok"><span className="dot" />on · {status.backup_codes_remaining} backup codes left</span>
              : <span className="badge neutral"><span className="dot" />off</span>}
          </span>
        </div>
      )}

      {msg && <div className={msg.ok ? "notice ok" : "error"} style={{ marginTop: 12 }}>{msg.text}</div>}
      {codes && <BackupCodes codes={codes} />}

      {/* Disabled → offer enable */}
      {status && !status.enabled && !setup && (
        <button className="btn primary" style={{ marginTop: 14 }} onClick={begin} disabled={busy}>
          {busy ? "Starting…" : "Enable two-factor"}
        </button>
      )}

      {/* Enrollment in progress */}
      {setup && (
        <div style={{ marginTop: 16 }}>
          <div className="cov-note" style={{ marginBottom: 12 }}>
            In your authenticator app, add an account and enter this setup key
            (or scan the URI below). Then type the 6-digit code it shows to confirm.
          </div>
          <div className="field">
            <label>Setup key</label>
            <div className="mfa-secret mono">{secretGrouped}</div>
          </div>
          <div className="field">
            <label>otpauth URI</label>
            <input className="mono" readOnly value={setup.otpauth_uri} onFocus={(e) => e.target.select()} />
          </div>
          <div className="field">
            <label>6-digit code</label>
            <input value={code} onChange={(e) => setCode(e.target.value)}
                   inputMode="numeric" autoComplete="one-time-code" placeholder="123456" />
          </div>
          <button className="btn primary" onClick={confirm} disabled={busy || code.length < 6}>
            {busy ? "Verifying…" : "Verify & turn on"}
          </button>
          <button className="btn" style={{ marginLeft: 8 }} onClick={() => { setSetup(null); setCode(""); }}>Cancel</button>
        </div>
      )}

      {/* Enabled → manage */}
      {status && status.enabled && !codes && (
        <div style={{ marginTop: 16 }}>
          <div className="field">
            <label>Confirm your password to make changes</label>
            <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} />
          </div>
          <button className="btn" onClick={regen} disabled={busy || !password}>Regenerate backup codes</button>
          <button className="btn" style={{ marginLeft: 8 }} onClick={disable} disabled={busy || !password}>Turn off</button>
        </div>
      )}
    </div>
  );
}

function Security() {
  const [form, setForm] = useState({ current_password: "", new_password: "", confirm: "" });
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState(null);
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });

  async function submit() {
    setMsg(null);
    if (form.new_password !== form.confirm) {
      setMsg({ ok: false, text: "New password and confirmation don't match." });
      return;
    }
    setSaving(true);
    try {
      await api.post("/users/change_password/", {
        current_password: form.current_password,
        new_password: form.new_password,
      });
      setForm({ current_password: "", new_password: "", confirm: "" });
      setMsg({ ok: true, text: "Password updated." });
    } catch (e) {
      const detail = e?.response?.data;
      const text =
        detail?.new_password?.[0] ||
        detail?.current_password?.[0] ||
        "Couldn't update password.";
      setMsg({ ok: false, text });
    } finally {
      setSaving(false);
    }
  }

  return (
    <>
      <div className="acct-panel">
        <h2>Password</h2>
        <p className="acct-sub">Change your password. Requires your current password.</p>
        <div className="field"><label>Current password</label><input type="password" value={form.current_password} onChange={set("current_password")} /></div>
        <div className="field"><label>New password</label><input type="password" value={form.new_password} onChange={set("new_password")} /></div>
        <div className="field"><label>Confirm new password</label><input type="password" value={form.confirm} onChange={set("confirm")} /></div>
        {msg && <div className={msg.ok ? "notice ok" : "error"}>{msg.text}</div>}
        <button className="btn primary" onClick={submit} disabled={saving}>{saving ? "Updating…" : "Update password"}</button>
      </div>
      <Mfa />
    </>
  );
}

function Notifications({ me }) {
  return (
    <div className="acct-panel">
      <h2>Notifications</h2>
      <p className="acct-sub">How review reminders reach you and your team.</p>
      <div className="info-list">
        <div className="info-row">
          <span className="info-k">Reminder address</span>
          <span className="info-v mono">{me?.email || "— add an email on the Profile tab —"}</span>
        </div>
        <div className="info-row">
          <span className="info-k">Documents you own</span>
          <span className="info-v">Email you before each document's review date, and again if it goes overdue.</span>
        </div>
        <div className="info-row">
          <span className="info-k">Delivery</span>
          <span className="info-v">Sent from the workspace mailbox (IMAP/POP3 + SMTP) or Amazon SES, per deployment.</span>
        </div>
      </div>
      <div className="cov-note">
        Review reminders are scheduled automatically from each document's review cadence.
        An administrator configures the lead times (e.g. 30, 14, 7, and 1 days before due).
      </div>
    </div>
  );
}

function Access({ me }) {
  const caps = me?.capabilities || {};
  return (
    <div className="acct-panel">
      <h2>Role &amp; access</h2>
      <p className="acct-sub">Your role determines what you can manage and which folders you can open.</p>
      <div className="info-row">
        <span className="info-k">Role</span>
        <span className="info-v"><span className="badge neutral">{me?.role_detail?.name || "No role"}</span></span>
      </div>
      {me?.role_detail?.description && <div className="cov-note">{me.role_detail.description}</div>}
      <div className="cap-title">Capabilities</div>
      <div className="cap-grid">
        {Object.keys(CAP_LABELS).map((k) => (
          <div className={"cap-item" + (caps[k] ? " on" : "")} key={k}>
            <span className="cap-mark">{caps[k] ? "✓" : "—"}</span>
            <span>{CAP_LABELS[k]}</span>
          </div>
        ))}
      </div>
      <div className="cov-note">
        Folder access is granted separately, per role or per user, and inherits down the folder tree.
        Contact an administrator to change your role or folder permissions.
      </div>
    </div>
  );
}

function About() {
  return (
    <div className="acct-panel">
      <h2>About</h2>
      <p className="acct-sub">Compliance management workspace.</p>
      <div className="info-list">
        <div className="info-row"><span className="info-k">Frameworks</span><span className="info-v">SOC 2 · ISO/IEC 27001:2022 · PCI DSS v4.0.1</span></div>
        <div className="info-row"><span className="info-k">Capabilities</span><span className="info-v">Control library, evidence folders, document reviews, review reminders, analytics.</span></div>
        <div className="info-row"><span className="info-k">Access model</span><span className="info-v">Role-based, with folder-level permissions inherited down the tree.</span></div>
      </div>
    </div>
  );
}

function Appearance() {
  const [theme, setThemeState] = useState(getTheme());
  const [accent, setAccentState] = useState(getAccent());

  function chooseTheme(id) {
    setTheme(id);
    setThemeState(id);
    setAccentState(getAccent());
  }
  function chooseAccent(hex) {
    setAccent(hex);
    setAccentState(hex || "");
  }

  return (
    <div className="acct-panel">
      <h2>Appearance</h2>
      <p className="acct-sub">
        Choose a theme and accent colour. Changes apply instantly and are
        remembered on this device.
      </p>

      <div className="cap-title">Theme</div>
      <div className="theme-grid">
        {THEMES.map((t) => (
          <div key={t.id} className={"theme-card" + (theme === t.id ? " active" : "")}
               onClick={() => chooseTheme(t.id)}>
            <div className="theme-chip" style={{ background: t.bg }}>
              <span className="bar" style={{ background: t.swatch }} />
            </div>
            <div>
              <div className="theme-name">{t.label}</div>
              <div className="theme-mode">{t.mode === "dark" ? "Dark" : "Light"}</div>
            </div>
          </div>
        ))}
      </div>

      <div className="cap-title">Accent colour</div>
      <div className="swatches">
        {ACCENT_PRESETS.map((p) => (
          <span key={p.hex}
                className={"swatch" + (accent.toLowerCase() === p.hex.toLowerCase() ? " active" : "")}
                style={{ background: p.hex }} title={p.name}
                onClick={() => chooseAccent(p.hex)} />
        ))}
        <input className="swatch-custom" type="color" value={accent || "#0f766e"}
               onChange={(e) => chooseAccent(e.target.value)} title="Custom colour" />
        {accent && <button className="btn small" onClick={() => chooseAccent("")}>Reset accent</button>}
      </div>
      <p className="hint">
        The accent recolours primary buttons, active navigation, links and
        highlights. Status colours (success, warning, overdue) stay fixed so
        they remain meaningful.
      </p>
    </div>
  );
}

export default function Account({ me, onUpdate }) {
  const [tab, setTab] = useState("profile");
  return (
    <div className="acct">
      <aside className="acct-nav">
        <div className="acct-id">
          <div className="acct-avatar">{(me?.full_name || me?.username || "?").slice(0, 1).toUpperCase()}</div>
          <div>
            <div className="acct-name">{me?.full_name || me?.username || "…"}</div>
            <div className="acct-role">{me?.role_detail?.name || "No role"}</div>
          </div>
        </div>
        {SECTIONS.map((s) => (
          <div
            key={s.key}
            className={"acct-tab" + (tab === s.key ? " active" : "")}
            onClick={() => setTab(s.key)}
          >
            <span className="acct-ic">{s.icon}</span> {s.label}
          </div>
        ))}
      </aside>
      <div className="acct-main">
        {tab === "profile" && <Profile me={me} onUpdate={onUpdate} />}
        {tab === "security" && <Security />}
        {tab === "notifications" && <Notifications me={me} />}
        {tab === "appearance" && <Appearance />}
        {tab === "access" && <Access me={me} />}
        {tab === "about" && <About />}
      </div>
    </div>
  );
}
