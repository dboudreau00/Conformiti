import { useEffect, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import {
  BellIcon,
  CheckIcon,
  ContrastIcon,
  DownloadIcon,
  ExternalLinkIcon,
  FingerprintIcon,
  InfoIcon,
  KeyRoundIcon,
  MinusIcon,
  RefreshCwIcon,
  ShieldIcon,
  UserIcon,
} from "lucide-react";
import api, { chooseWorkspace, fetchAll } from "../api/client.js";
import { createPasskey, passkeyErrorText, passkeysSupported } from "../api/webauthn.js";
import { ACCENT_PACKS, THEME_PACKS, accentHex, useTheme } from "../theme.js";
import { useShell } from "../shell.js";
import { cn } from "../utils/cn.js";
import { errorText } from "../utils/a11y.js";
import { EASE, PanelTransition, Stack, StackItem } from "../components/layout/PanelTransition.jsx";
import { Badge } from "../components/ui/Badge.jsx";
import { Button } from "../components/ui/Button.jsx";
import { Divider, Empty, Label, Loading, Panel, PanelHeader } from "../components/ui/Panel.jsx";

const SECTIONS = [
  { id: "profile", label: "Profile", icon: UserIcon },
  { id: "appearance", label: "Appearance", icon: ContrastIcon },
  { id: "security", label: "Security", icon: KeyRoundIcon },
  { id: "notifications", label: "Notifications", icon: BellIcon },
  { id: "access", label: "Role & access", icon: ShieldIcon },
  { id: "about", label: "About", icon: InfoIcon },
];

const CAP_LABELS = {
  manage_users: "Manage users & roles",
  manage_frameworks: "Manage frameworks & controls",
  manage_documents: "Manage document library",
  manage_folders: "Manage folders & permissions",
  view_all: "View all folders (bypass restrictions)",
  auditor: "Auditor (read-only)",
};

const DOCS_URL = "https://github.com/dboudreau00/Conformiti";
const isHex = (v) => /^#[0-9a-f]{6}$/i.test(v || "");

/* ---------- small page-private helpers ---------- */

function SectionTitle({ title, badge, children }) {
  return (
    <>
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="text-[17px] font-semibold tracking-[-0.015em] text-ink">{title}</h2>
        {badge}
      </div>
      {children ? <p className="mt-1 max-w-[62ch] text-[13px] leading-snug text-muted">{children}</p> : null}
    </>
  );
}

function SubTitle({ title, children }) {
  return (
    <>
      <h3 className="text-[14px] font-semibold tracking-[-0.01em] text-ink">{title}</h3>
      {children ? <p className="mt-1 max-w-[62ch] text-[13px] leading-snug text-muted">{children}</p> : null}
    </>
  );
}

function Field({ id, label, hint, error = false, className, children }) {
  return (
    <div className={className}>
      <label htmlFor={id} className="field-label">
        {label}
      </label>
      {children}
      {hint ? <p className={cn("mt-1.5 text-xs", error ? "text-danger" : "text-muted")}>{hint}</p> : null}
    </div>
  );
}

function Notice({ msg, className }) {
  if (!msg) return null;
  return (
    <div className={cn("notice", msg.ok ? "notice-ok" : "notice-err", className)} role={msg.ok ? "status" : "alert"}>
      {msg.text}
    </div>
  );
}

/* ---------- Profile ---------- */

const pickProfile = (u) => ({
  first_name: u?.first_name || "",
  last_name: u?.last_name || "",
  email: u?.email || "",
  job_title: u?.job_title || "",
});

function ProfileSection({ me, onUpdate }) {
  const [form, setForm] = useState(() => pickProfile(me));
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState(null);

  // `me` loads asynchronously; if the user lands directly on /settings the form
  // mounts before the profile arrives, so sync the fields when it does.
  useEffect(() => {
    setForm(pickProfile(me));
  }, [me?.id]);

  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  async function save(e) {
    e.preventDefault();
    setSaving(true);
    setMsg(null);
    try {
      const { data } = await api.patch("/users/me/", form);
      onUpdate?.(data);
      setMsg({ ok: true, text: "Profile saved." });
    } catch (err) {
      setMsg({ ok: false, text: errorText(err, "Couldn't save. Check the fields and try again.") });
    } finally {
      setSaving(false);
    }
  }

  if (!me) {
    return (
      <Panel>
        <Loading />
      </Panel>
    );
  }

  return (
    <Panel className="p-5">
      <SectionTitle title="Profile">How you appear across the workspace and on documents you own.</SectionTitle>
      <form onSubmit={save} noValidate className="mt-5 grid max-w-[640px] grid-cols-1 gap-4 sm:grid-cols-2">
        <Field id="acct-first" label="First name">
          <input id="acct-first" className="input" autoComplete="given-name" value={form.first_name} onChange={set("first_name")} />
        </Field>
        <Field id="acct-last" label="Last name">
          <input id="acct-last" className="input" autoComplete="family-name" value={form.last_name} onChange={set("last_name")} />
        </Field>
        <Field id="acct-email" label="Email" className="sm:col-span-2">
          <input id="acct-email" type="email" className="input" autoComplete="email" value={form.email} onChange={set("email")} />
        </Field>
        <Field id="acct-title" label="Job title" className="sm:col-span-2">
          <input id="acct-title" className="input" autoComplete="organization-title" placeholder="e.g. Security Analyst" value={form.job_title} onChange={set("job_title")} />
        </Field>
        <Field id="acct-username" label="Username" className="sm:col-span-2" hint="Usernames are managed by an administrator.">
          <input id="acct-username" className="input font-mono" value={me.username || ""} disabled />
        </Field>
        <div className="flex flex-col items-start gap-3 sm:col-span-2">
          <Notice msg={msg} className="w-full" />
          <Button type="submit" variant="primary" disabled={saving}>
            {saving ? "Saving…" : "Save changes"}
          </Button>
        </div>
      </form>
    </Panel>
  );
}

/* ---------- Appearance ---------- */

function AppearanceSection() {
  const { theme, accent, setTheme, setAccent } = useTheme();
  const custom = isHex(accent);
  const [hex, setHex] = useState(() => accentHex(accent));

  // Keep the picker in step when the accent changes elsewhere (top bar, another tab).
  useEffect(() => {
    setHex(accentHex(accent));
  }, [accent]);

  const canApply = isHex(hex) && hex.toLowerCase() !== (custom ? accent : "");

  return (
    <Panel className="p-5">
      <SectionTitle title="Appearance">
        Theme packs recolour every surface and chart at once; the accent recolours primary buttons, active navigation and
        highlights. Status colours — success, warning, overdue — stay fixed so they remain meaningful in evidence exports.
        Changes apply instantly and are remembered on this device.
      </SectionTitle>

      <Label as="p" className="mb-2.5 mt-5">Theme pack</Label>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2" role="group" aria-label="Theme pack">
        {THEME_PACKS.map((pack) => {
          const on = pack.id === theme;
          return (
            <button
              key={pack.id}
              type="button"
              onClick={() => setTheme(pack.id)}
              aria-pressed={on}
              className={cn(
                "relative flex items-center gap-3 rounded-xl border p-3 text-left",
                "transition-[border-color,background-color] duration-150 ease-out",
                on ? "border-accent bg-accent/[0.06]" : "border-line hover:border-line-strong"
              )}
            >
              <span className="flex h-11 w-11 shrink-0 overflow-hidden rounded-lg ring-1 ring-line-strong" aria-hidden="true">
                <span className="h-full w-1/2" style={{ background: pack.swatch[0] }} />
                <span className="h-full w-1/2" style={{ background: pack.swatch[1] }} />
              </span>
              <span className="min-w-0 flex-1">
                <span className="flex items-center gap-2">
                  <span className="text-[13px] font-semibold text-ink">{pack.name}</span>
                  <Badge tone="muted" mono>
                    {pack.mode}
                  </Badge>
                </span>
                <span className="mt-0.5 block text-xs leading-snug text-muted">{pack.blurb}</span>
              </span>
              {on ? (
                <motion.span
                  layoutId="theme-check"
                  className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-accent"
                  transition={{ type: "spring", stiffness: 520, damping: 36 }}
                  aria-hidden="true"
                >
                  <CheckIcon className="h-3 w-3 text-accent-ink" strokeWidth={3} />
                </motion.span>
              ) : null}
            </button>
          );
        })}
      </div>

      <Label as="p" className="mb-2.5 mt-6">Accent pack</Label>
      <div className="flex flex-wrap gap-2" role="group" aria-label="Accent pack">
        {ACCENT_PACKS.map((a) => {
          const on = a.id === accent;
          return (
            <button
              key={a.id}
              type="button"
              onClick={() => setAccent(a.id)}
              aria-pressed={on}
              className={cn(
                "flex items-center gap-2 rounded-lg border px-3 py-2 text-[13px] font-medium",
                "transition-[border-color,background-color] duration-150 ease-out",
                on ? "border-accent bg-accent/[0.06] text-ink" : "border-line text-muted hover:border-line-strong"
              )}
            >
              <span className="h-4 w-4 rounded-full ring-1 ring-line-strong" style={{ background: a.hex }} aria-hidden="true" />
              {a.name}
            </button>
          );
        })}
      </div>

      <div className={cn("mt-3 flex flex-wrap items-center gap-2 rounded-lg border px-3 py-2", custom ? "border-accent bg-accent/[0.06]" : "border-line")}>
        <label htmlFor="acct-accent-custom" className="flex items-center gap-2 text-[13px] font-medium text-ink">
          <input
            id="acct-accent-custom"
            type="color"
            value={hex}
            onChange={(e) => setHex(e.target.value)}
            className="h-7 w-9 cursor-pointer rounded-md border border-line bg-surface p-0.5"
          />
          Custom
          {custom ? (
            <Badge tone="accent" mono>
              active
            </Badge>
          ) : null}
        </label>
        <span className="font-mono text-2xs uppercase tracking-label text-faint">{hex}</span>
        <div className="ml-auto flex items-center gap-2">
          <Button size="sm" onClick={() => setAccent(hex.toLowerCase())} disabled={!canApply}>
            Use custom colour
          </Button>
          {custom ? (
            <Button size="sm" variant="ghost" onClick={() => setAccent("")}>
              Reset accent
            </Button>
          ) : null}
        </div>
      </div>

      <div className="mt-6 rounded-xl border border-line bg-surface-2 p-4">
        <Label as="p" className="mb-2">Live preview</Label>
        <div className="flex flex-wrap items-center gap-2">
          <Button variant="primary" size="sm">
            Primary action
          </Button>
          <Button size="sm">Secondary</Button>
          <Badge tone="success" dot>
            Implemented
          </Badge>
          <Badge tone="warning" dot>
            In progress
          </Badge>
          <Badge tone="danger" dot>
            3d overdue
          </Badge>
          <span className="font-mono text-2xs uppercase tracking-label text-faint">SOC 2 / CC6.1</span>
        </div>
      </div>
    </Panel>
  );
}

/* ---------- Security ---------- */

function PasswordBlock() {
  const [form, setForm] = useState({ current_password: "", new_password: "", confirm: "" });
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState(null);
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));
  const mismatch = form.confirm.length > 0 && form.new_password !== form.confirm;

  async function submit(e) {
    e.preventDefault();
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
    } catch (err) {
      const detail = err?.response?.data;
      const text = detail?.new_password?.[0] || detail?.current_password?.[0] || errorText(err, "Couldn't update password.");
      setMsg({ ok: false, text });
    } finally {
      setSaving(false);
    }
  }

  return (
    <>
      <SubTitle title="Password">Change your password. Requires your current password.</SubTitle>
      <form onSubmit={submit} noValidate className="mt-4 grid max-w-[640px] grid-cols-1 gap-4 sm:grid-cols-2">
        <Field id="pw-current" label="Current password" className="sm:col-span-2">
          <input id="pw-current" type="password" autoComplete="current-password" className="input sm:max-w-[312px]" value={form.current_password} onChange={set("current_password")} />
        </Field>
        <Field id="pw-new" label="New password">
          <input id="pw-new" type="password" autoComplete="new-password" className="input" value={form.new_password} onChange={set("new_password")} />
        </Field>
        <Field id="pw-confirm" label="Confirm new password" hint={mismatch ? "Doesn't match the new password." : undefined} error={mismatch}>
          <input
            id="pw-confirm"
            type="password"
            autoComplete="new-password"
            aria-invalid={mismatch || undefined}
            className={cn("input", mismatch && "border-danger focus:border-danger")}
            value={form.confirm}
            onChange={set("confirm")}
          />
        </Field>
        <div className="flex flex-col items-start gap-3 sm:col-span-2">
          <Notice msg={msg} className="w-full" />
          <Button type="submit" variant="primary" disabled={saving || !form.current_password || !form.new_password || !form.confirm}>
            {saving ? "Updating…" : "Update password"}
          </Button>
        </div>
      </form>
    </>
  );
}

function BackupCodes({ codes }) {
  function download() {
    const text = "Conformiti — backup codes\n" + "Each code works once. Keep them somewhere safe.\n\n" + codes.join("\n") + "\n";
    const url = URL.createObjectURL(new Blob([text], { type: "text/plain" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = "compliance-backup-codes.txt";
    a.click();
    URL.revokeObjectURL(url);
  }
  return (
    <div className="mt-4 max-w-[640px] rounded-xl border border-success/25 bg-success/10 p-4" role="status">
      <p className="text-[13px] font-semibold text-success">Save your backup codes</p>
      <p className="mt-1 text-xs leading-snug text-muted">Each code can be used once if you lose your authenticator. They won't be shown again.</p>
      <ul className="mt-3 grid grid-cols-2 gap-x-4 gap-y-1.5 font-mono text-[13px] tracking-wide text-ink sm:grid-cols-3">
        {codes.map((c) => (
          <li key={c} className="tabular select-all">
            {c}
          </li>
        ))}
      </ul>
      <Button size="sm" className="mt-3" onClick={download} icon={<DownloadIcon className="h-3.5 w-3.5" strokeWidth={2} aria-hidden="true" />}>
        Download .txt
      </Button>
    </div>
  );
}

function MfaBlock() {
  const [status, setStatus] = useState(null); // {enabled, pending, backup_codes_remaining}
  const [statusErr, setStatusErr] = useState(null);
  const [setup, setSetup] = useState(null); // {secret, otpauth_uri}
  const [code, setCode] = useState("");
  const [password, setPassword] = useState("");
  const [codes, setCodes] = useState(null); // freshly issued backup codes
  const [msg, setMsg] = useState(null);
  const [busy, setBusy] = useState(false);

  function loadStatus() {
    setStatusErr(null);
    api
      .get("/auth/mfa/status/")
      .then((r) => setStatus(r.data))
      .catch((e) => {
        setStatus(null);
        setStatusErr(errorText(e, "Couldn't load two-factor status."));
      });
  }
  useEffect(() => {
    loadStatus();
  }, []);

  async function begin() {
    setMsg(null);
    setCodes(null);
    setBusy(true);
    try {
      const { data } = await api.post("/auth/mfa/setup/");
      setSetup(data);
    } catch (e) {
      setMsg({ ok: false, text: errorText(e, "Couldn't start setup.") });
    } finally {
      setBusy(false);
    }
  }

  async function confirm(e) {
    e.preventDefault();
    setMsg(null);
    setBusy(true);
    try {
      const { data } = await api.post("/auth/mfa/verify/", { code: code.trim() });
      setCodes(data.backup_codes || null);
      setSetup(null);
      setCode("");
      loadStatus();
      setMsg({ ok: true, text: data.backup_codes
        ? "Two-factor authentication is on."
        : `Two-factor authentication is on. Your existing ${data.backup_codes_remaining} backup codes still work.` });
    } catch (err) {
      setMsg({ ok: false, text: errorText(err, "That code isn't valid.") });
    } finally {
      setBusy(false);
    }
  }

  async function disable() {
    setMsg(null);
    setBusy(true);
    try {
      await api.post("/auth/mfa/disable/", { password });
      setPassword("");
      setCodes(null);
      loadStatus();
      setMsg({ ok: true, text: "Two-factor authentication is off." });
    } catch (e) {
      setMsg({ ok: false, text: errorText(e, "Couldn't disable MFA.") });
    } finally {
      setBusy(false);
    }
  }

  async function regen() {
    setMsg(null);
    setBusy(true);
    try {
      const { data } = await api.post("/auth/mfa/backup-codes/", { password });
      setCodes(data.backup_codes);
      setPassword("");
      loadStatus();
      setMsg({ ok: true, text: "New backup codes issued. The old ones no longer work." });
    } catch (e) {
      setMsg({ ok: false, text: errorText(e, "Couldn't regenerate codes.") });
    } finally {
      setBusy(false);
    }
  }

  function cancelSetup() {
    setSetup(null);
    setCode("");
    setMsg(null);
  }

  const secretGrouped = setup?.secret ? setup.secret.replace(/(.{4})/g, "$1 ").trim() : "";
  const remaining = status?.backup_codes_remaining ?? 0;

  return (
    <>
      <SubTitle title="Two-factor authentication">
        Add a one-time code from an authenticator app (Google Authenticator, Authy, 1Password, Microsoft Authenticator) to your sign-in.
      </SubTitle>

      {statusErr ? (
        <div className="mt-4 flex max-w-[640px] flex-wrap items-center gap-3">
          <div className="notice notice-err flex-1" role="alert">
            {statusErr}
          </div>
          <Button size="sm" onClick={loadStatus}>
            Retry
          </Button>
        </div>
      ) : !status ? (
        <Loading className="py-6 text-left" />
      ) : (
        <ul className="mt-4 max-w-[640px] divide-y divide-line rounded-xl border border-line">
          <li className="flex flex-wrap items-center gap-x-4 gap-y-2 px-4 py-3">
            <span className="min-w-0 flex-1">
              <span className="block text-[13px] font-medium text-ink">Authenticator app</span>
              <span className="block text-xs text-muted">
                {status.enabled ? "Enrolled · TOTP" : setup || status.pending ? "Enrolment started, not yet verified" : "Not enrolled"}
              </span>
            </span>
            <Badge tone={status.enabled ? "success" : "muted"} dot>
              {status.enabled ? `On · ${remaining} backup ${remaining === 1 ? "code" : "codes"} left`
                : status.second_factor ? `Off · ${remaining} backup ${remaining === 1 ? "code" : "codes"} left (passkey)` : "Off"}
            </Badge>
            {!status.enabled && !setup ? (
              <Button size="sm" variant="primary" onClick={begin} disabled={busy}>
                {busy ? "Starting…" : "Enable"}
              </Button>
            ) : null}
          </li>
        </ul>
      )}

      <Notice msg={msg} className="mt-4 max-w-[640px]" />
      {codes ? <BackupCodes codes={codes} /> : null}

      {/* Enrolment in progress */}
      {setup ? (
        <form onSubmit={confirm} noValidate className="mt-4 max-w-[640px] rounded-xl border border-line bg-surface-2 p-4">
          <p className="text-[13px] leading-snug text-muted">
            In your authenticator app, add an account and enter this setup key (or paste the URI below). Then type the 6-digit code it shows to confirm.
          </p>
          <div className="mt-4 grid grid-cols-1 gap-4">
            <div>
              <Label as="p" className="mb-1.5">Setup key</Label>
              <p className="select-all rounded-lg border border-line bg-surface px-3 py-2 font-mono text-[13px] tracking-[0.14em] text-ink">{secretGrouped}</p>
            </div>
            <Field id="mfa-uri" label="otpauth URI">
              <input id="mfa-uri" className="input font-mono text-xs" readOnly value={setup.otpauth_uri} onFocus={(e) => e.target.select()} />
            </Field>
            <Field id="mfa-code" label="6-digit code">
              <input
                id="mfa-code"
                className="input font-mono sm:max-w-[200px]"
                value={code}
                onChange={(e) => setCode(e.target.value)}
                inputMode="numeric"
                autoComplete="one-time-code"
                placeholder="123456"
                maxLength={8}
                autoFocus
              />
            </Field>
          </div>
          <div className="mt-4 flex flex-wrap items-center gap-2">
            <Button type="submit" variant="primary" disabled={busy || code.trim().length < 6}>
              {busy ? "Verifying…" : "Verify & turn on"}
            </Button>
            <Button variant="ghost" onClick={cancelSetup} disabled={busy}>
              Cancel
            </Button>
          </div>
        </form>
      ) : null}

      {/* A second factor of either kind → manage backup codes; the app → turn off */}
      {status?.second_factor && !codes ? (
        <div className="mt-4 max-w-[640px]">
          <Field id="mfa-password" label="Confirm your password to make changes">
            <input
              id="mfa-password"
              type="password"
              autoComplete="current-password"
              className="input sm:max-w-[312px]"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </Field>
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <Button onClick={regen} disabled={busy || !password} icon={<RefreshCwIcon className="h-3.5 w-3.5" strokeWidth={2} aria-hidden="true" />}>
              Regenerate backup codes
            </Button>
            {status.enabled ? (
              <Button variant="danger" onClick={disable} disabled={busy || !password}>
                Turn off
              </Button>
            ) : null}
          </div>
          {!status.enabled ? (
            <p className="mt-2 text-xs text-muted">Backup codes belong to your account: they work beside your passkeys too.</p>
          ) : null}
        </div>
      ) : null}
    </>
  );
}

/** Passkeys and security keys as a second factor. Enrolling one is a browser
 * ceremony (the server issues a challenge, the authenticator signs it);
 * removing one takes the account password, so a hijacked session cannot
 * quietly strip a factor. A key the server has flagged as possibly cloned is
 * shown as such and can only be removed. */
function PasskeysBlock() {
  const [state, setState] = useState(null); // {results, factors, rp_id, max}
  const [loadErr, setLoadErr] = useState(null);
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [msg, setMsg] = useState(null);
  const [busy, setBusy] = useState(false);
  const [codes, setCodes] = useState(null); // backup codes issued with the first factor
  const supported = passkeysSupported();

  function load() {
    setLoadErr(null);
    api.get("/auth/webauthn/")
      .then((r) => setState(r.data))
      .catch((e) => { setState(null); setLoadErr(errorText(e, "Couldn't load passkeys.")); });
  }
  useEffect(() => { load(); }, []);

  async function add(e) {
    e.preventDefault();
    setMsg(null);
    setBusy(true);
    try {
      const { data } = await api.post("/auth/webauthn/register/options/");
      const credential = await createPasskey(data.options);
      const done = await api.post("/auth/webauthn/register/", { state: data.state, name: name.trim(), credential });
      setName("");
      setCodes(done.data?.backup_codes || null);
      load();
      setMsg({ ok: true, text: done.data?.backup_codes
        ? "Passkey enrolled. Save the backup codes below: they are the way back in if you lose this key."
        : "Passkey enrolled. Signing in now takes your password and this key." });
    } catch (err) {
      setMsg({ ok: false, text: passkeyErrorText(err) });
    } finally {
      setBusy(false);
    }
  }

  async function remove(row) {
    setMsg(null);
    setBusy(true);
    try {
      await api.delete(`/auth/webauthn/${row.id}/`, { data: { password } });
      setPassword("");
      load();
      setMsg({ ok: true, text: `Removed "${row.name}".` });
    } catch (err) {
      setMsg({ ok: false, text: errorText(err, "Couldn't remove the passkey.") });
    } finally {
      setBusy(false);
    }
  }

  async function rename(row) {
    const next = window.prompt("Name this passkey", row.name);
    if (!next || next.trim() === row.name) return;
    try {
      await api.patch(`/auth/webauthn/${row.id}/`, { name: next.trim() });
      load();
    } catch (err) {
      setMsg({ ok: false, text: errorText(err, "Couldn't rename the passkey.") });
    }
  }

  const rows = state?.results || [];
  const suspect = rows.filter((r) => !r.usable).length;

  return (
    <>
      <SubTitle title="Passkeys and security keys">
        Phishing-resistant sign-in with a passkey (Touch ID, Windows Hello, a phone) or a hardware security key. Works alongside, or instead of, the authenticator app.
      </SubTitle>
      {loadErr ? (
        <div className="mt-4 flex max-w-[640px] flex-wrap items-center gap-3">
          <div className="notice notice-err flex-1" role="alert">{loadErr}</div>
          <Button size="sm" onClick={load}>Retry</Button>
        </div>
      ) : !state ? (
        <Loading className="py-6 text-left" />
      ) : (
        <>
          {suspect ? (
            <div className="notice notice-err mt-4 max-w-[640px]" role="alert">
              {suspect === 1 ? "One passkey was" : `${suspect} passkeys were`} disabled because the signature counter went backwards, which means a copy of the key may exist. Remove {suspect === 1 ? "it" : "them"} with your password and enrol a fresh key.
            </div>
          ) : null}
          <ul className="mt-4 max-w-[640px] divide-y divide-line rounded-xl border border-line" aria-label="Enrolled passkeys">
            {rows.length === 0 ? (
              <li className="px-4 py-3 text-xs text-muted">No passkeys enrolled.</li>
            ) : rows.map((r) => (
              <li key={r.id} className="flex flex-wrap items-center gap-x-4 gap-y-2 px-4 py-3">
                <FingerprintIcon className={cn("h-4 w-4 shrink-0", r.usable ? "text-muted" : "text-danger")} strokeWidth={1.75} aria-hidden="true" />
                <span className="min-w-0 flex-1">
                  <span className="block text-[13px] font-medium text-ink">{r.name}</span>
                  <span className="block text-xs text-muted">
                    {r.algorithm}{r.backup_eligible ? " · synced passkey" : " · device-bound"}
                    {" · added "}{String(r.created_at).slice(0, 10)}
                    {r.last_used_at ? ` · last used ${String(r.last_used_at).slice(0, 10)}` : " · never used"}
                  </span>
                  {!r.usable ? <span className="block text-xs text-danger">{r.suspect_reason}</span> : null}
                </span>
                <Badge tone={r.usable ? "success" : "danger"} dot>{r.usable ? "Active" : "Disabled"}</Badge>
                {r.usable ? <Button size="sm" variant="ghost" onClick={() => rename(r)} disabled={busy}>Rename</Button> : null}
                <Button size="sm" variant="danger" onClick={() => remove(r)} disabled={busy || !password} title={password ? "" : "Confirm your password below first"}>
                  Remove
                </Button>
              </li>
            ))}
          </ul>
        </>
      )}
      <Notice msg={msg} className="mt-4 max-w-[640px]" />
      {codes ? <BackupCodes codes={codes} /> : null}
      {state && supported && rows.length < (state.max || 10) ? (
        <form onSubmit={add} noValidate className="mt-4 flex max-w-[640px] flex-wrap items-end gap-2">
          <Field id="passkey-name" label="Name for the new key" className="min-w-[220px] flex-1">
            <input id="passkey-name" className="input" value={name} placeholder="Work laptop" maxLength={80}
                   onChange={(e) => setName(e.target.value)} />
          </Field>
          <Button type="submit" variant="primary" disabled={busy}
                  icon={<FingerprintIcon className="h-3.5 w-3.5" strokeWidth={2} aria-hidden="true" />}>
            {busy ? "Waiting for your authenticator…" : "Add passkey"}
          </Button>
        </form>
      ) : state && !supported ? (
        <p className="mt-3 max-w-[640px] text-xs text-muted">This browser cannot enrol passkeys (it needs a secure https address and a modern browser).</p>
      ) : null}
      {rows.length ? (
        <div className="mt-4 max-w-[640px]">
          <Field id="passkey-password" label="Confirm your password to remove a key">
            <input id="passkey-password" type="password" autoComplete="current-password" className="input sm:max-w-[312px]"
                   value={password} onChange={(e) => setPassword(e.target.value)} />
          </Field>
          <p className="mt-2 text-xs text-muted">
            Recovery if you lose this key: your backup codes (issued with your first factor; regenerate them under the authenticator block), a second passkey, the authenticator app, or an administrator's reset.
          </p>
        </div>
      ) : null}
    </>
  );
}

function SecuritySection() {
  return (
    <Panel className="p-5">
      <SectionTitle title="Security">Authentication factors on this account: your password, an optional authenticator app, and optional passkeys or security keys.</SectionTitle>
      <div className="mt-5">
        <PasswordBlock />
      </div>
      <Divider className="my-6" />
      <MfaBlock />
      <Divider className="my-6" />
      <PasskeysBlock />
    </Panel>
  );
}

/* ---------- Notifications ---------- */

/** The emailed digest of the person's own tray, and the chat channels the
 * deployment posts to (configured by an operator; an administrator can send
 * a test message and see the last deliveries). */
function ChannelsBlock({ me, onUpdate }) {
  const [info, setInfo] = useState(null);
  const [digest, setDigest] = useState(me?.digest || "off");
  const [msg, setMsg] = useState(null);
  const [busy, setBusy] = useState(false);
  const admin = !!(me?.is_superuser || me?.capabilities?.manage_users);

  const load = () => api.get("/notifications/channels/").then((r) => { setInfo(r.data); setDigest(r.data.digest); }).catch(() => setInfo({ slack: false, teams: false, events: [] }));
  useEffect(() => { load(); }, []);

  async function saveDigest(value) {
    setDigest(value);
    setMsg(null);
    setBusy(true);
    try {
      const { data } = await api.patch("/users/me/", { digest: value });
      onUpdate?.(data);
      setMsg({ ok: true, text: value === "off" ? "Digest emails are off." : `You'll get a ${value} digest of your tray by email.` });
    } catch (e) {
      setMsg({ ok: false, text: errorText(e, "Couldn't save the preference.") });
    } finally {
      setBusy(false);
    }
  }

  async function sendTest() {
    setMsg(null);
    setBusy(true);
    try {
      const { data } = await api.post("/notifications/channels/", {});
      const failed = (data.results || []).filter((r) => !r.ok);
      setMsg(failed.length
        ? { ok: false, text: `Delivery failed for ${failed.map((r) => `${r.channel} (${r.error || r.response_code})`).join(", ")}.` }
        : { ok: true, text: `Test message delivered to ${data.attempted.join(" and ")}.` });
      load();
    } catch (e) {
      setMsg({ ok: false, text: errorText(e, "Couldn't send the test message.") });
    } finally {
      setBusy(false);
    }
  }

  const choices = info?.digest_choices || [{ id: "off", label: "Off" }, { id: "daily", label: "Daily" }, { id: "weekly", label: "Weekly (Monday)" }];
  return (
    <>
      <div className="grid grid-cols-1 gap-1 px-5 py-3 sm:grid-cols-[200px_1fr] sm:gap-4">
        <span className="text-[13px] font-medium text-ink">Digest of your tray</span>
        <span className="text-[13px] leading-snug text-muted">
          <select id="digest-cadence" className="input sm:max-w-[240px]" value={digest} disabled={busy} aria-label="Digest cadence"
                  onChange={(e) => saveDigest(e.target.value)}>
            {choices.map((c) => <option key={c.id} value={c.id}>{c.label}</option>)}
          </select>
          <span className="mt-1.5 block text-xs">Everything in your notification tray, by email, at the morning scan. Nothing is sent when the tray is empty.</span>
        </span>
      </div>
      <div className="grid grid-cols-1 gap-1 border-t border-line px-5 py-3 sm:grid-cols-[200px_1fr] sm:gap-4">
        <span className="text-[13px] font-medium text-ink">Chat channels</span>
        <span className="text-[13px] leading-snug text-muted">
          {!info ? "…" : (
            <>
              <span className="flex flex-wrap items-center gap-1.5">
                <Badge tone={info.slack ? "success" : "muted"} dot>Slack {info.slack ? "configured" : "not configured"}</Badge>
                <Badge tone={info.teams ? "success" : "muted"} dot>Teams {info.teams ? "configured" : "not configured"}</Badge>
                {admin && (info.slack || info.teams) ? (
                  <Button size="sm" onClick={sendTest} disabled={busy}>{busy ? "Sending…" : "Send a test message"}</Button>
                ) : null}
              </span>
              <span className="mt-1.5 block text-xs">
                Sealed and issued packages, the auditor's returns and requests, returned questionnaires, scanner outages, quarantined files and a daily summary are posted to the channels an operator configures with SLACK_WEBHOOK_URL / TEAMS_WEBHOOK_URL.
              </span>
              {admin && info.deliveries?.length ? (
                <span className="mt-2 block font-mono text-2xs text-faint">
                  Last deliveries: {info.deliveries.slice(0, 5).map((d) => `${d.channel} ${d.event} ${d.ok ? "ok" : `failed${d.error ? ` (${d.error})` : ""}`}`).join(" · ")}
                </span>
              ) : null}
            </>
          )}
        </span>
      </div>
      {msg ? <div className="px-5 pb-3"><Notice msg={msg} /></div> : null}
    </>
  );
}

function NotificationsSection({ me, onGoProfile, onUpdate }) {
  if (!me) {
    return (
      <Panel>
        <Loading />
      </Panel>
    );
  }
  const rows = [
    {
      k: "Reminder address",
      v: me.email ? (
        <span className="font-mono text-xs text-ink">{me.email}</span>
      ) : (
        <span>
          No email on file —{" "}
          <button type="button" className="link" onClick={onGoProfile}>
            add one on the Profile tab
          </button>
        </span>
      ),
    },
    { k: "Documents you own", v: "Email before each document's review date, and again if it goes overdue." },
    {
      k: "When reminders fire",
      v: "Scheduled automatically from each document's review cadence. An administrator sets the lead times (e.g. 30, 14, 7 and 1 days before due).",
    },
    { k: "Delivery channel", v: "Email, sent from the workspace mailbox (IMAP/POP3 + SMTP) or Amazon SES, per deployment." },
  ];
  return (
    <Panel className="overflow-hidden">
      <PanelHeader title="Notifications" meta="Reminders, digests and chat" />
      <ul className="divide-y divide-line">
        {rows.map((r, i) => (
          <motion.li
            key={r.k}
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.2, ease: EASE, delay: i * 0.03 }}
            className="grid grid-cols-1 gap-1 px-5 py-3 sm:grid-cols-[200px_1fr] sm:gap-4"
          >
            <span className="text-[13px] font-medium text-ink">{r.k}</span>
            <span className="text-[13px] leading-snug text-muted">{r.v}</span>
          </motion.li>
        ))}
      </ul>
      <div className="border-t border-line">
        <ChannelsBlock me={me} onUpdate={onUpdate} />
      </div>
      <p className="border-t border-line px-5 py-3 text-xs text-muted">
        Review reminders are configured per deployment by an administrator; the digest is yours to switch on.
      </p>
    </Panel>
  );
}

/* ---------- Role & access ---------- */

function AccessSection({ me }) {
  if (!me) {
    return (
      <Panel>
        <Loading />
      </Panel>
    );
  }
  const caps = me.capabilities || {};
  const role = me.role_detail;
  return (
    <Panel className="p-5">
      <SectionTitle title="Role & access">Your role determines what you can manage and which folders you can open.</SectionTitle>
      <dl className="mt-5 grid max-w-[720px] grid-cols-1 gap-4 sm:grid-cols-2">
        <div className="rounded-xl border border-line bg-surface-2 p-4">
          <dt>
            <Label>Role</Label>
          </dt>
          <dd className="mt-1.5">
            <span className="flex flex-wrap items-center gap-1.5">
              <Badge tone={role ? "accent" : "muted"}>{role?.name || "No role"}</Badge>
              {me.is_superuser ? (
                <Badge tone="warning" mono>
                  superuser
                </Badge>
              ) : null}
            </span>
            {role?.description ? <p className="mt-2 text-[13px] leading-snug text-muted">{role.description}</p> : null}
          </dd>
        </div>
        <div className="rounded-xl border border-line bg-surface-2 p-4">
          <dt>
            <Label>Signs in as</Label>
          </dt>
          <dd className="mt-1.5 font-mono text-[13px] text-ink">{me.username}</dd>
          <p className="mt-2 text-xs leading-snug text-muted">Usernames and roles are assigned by an administrator.</p>
        </div>
      </dl>

      <Label as="p" className="mb-2.5 mt-6">Capabilities</Label>
      <ul className="grid max-w-[720px] grid-cols-1 gap-2 sm:grid-cols-2">
        {Object.entries(CAP_LABELS).map(([k, label]) => {
          const on = !!caps[k];
          return (
            <li
              key={k}
              className={cn(
                "flex items-center gap-2.5 rounded-lg border px-3 py-2 text-[13px]",
                on ? "border-line bg-surface text-ink" : "border-line/60 text-muted"
              )}
            >
              <span
                className={cn(
                  "flex h-5 w-5 shrink-0 items-center justify-center rounded-full",
                  on ? "bg-success/[0.14] text-success" : "bg-surface-2 text-faint"
                )}
                aria-hidden="true"
              >
                {on ? <CheckIcon className="h-3 w-3" strokeWidth={3} /> : <MinusIcon className="h-3 w-3" strokeWidth={2.5} />}
              </span>
              <span>{label}</span>
              <span className="sr-only">{on ? "granted" : "not granted"}</span>
            </li>
          );
        })}
      </ul>
      <p className="mt-5 max-w-[62ch] text-xs leading-snug text-muted">
        Folder access is granted separately, per role or per user, and inherits down the folder tree. Contact an administrator to change your
        role or folder permissions.
      </p>
      <WorkspacesBlock me={me} />
    </Panel>
  );
}

/* ---------- Workspaces ---------- */

function WorkspacesBlock({ me }) {
  const [current, setCurrent] = useState(null);
  const [list, setList] = useState(null);
  const [name, setName] = useState("");
  const [withFrameworks, setWithFrameworks] = useState(true);
  const [msg, setMsg] = useState(null);
  const [busy, setBusy] = useState(false);
  const superuser = !!me?.is_superuser;

  const load = () => {
    api.get("/workspaces/current/").then((r) => setCurrent(r.data || null)).catch(() => setCurrent(null));
    if (superuser) api.get("/workspaces/", { params: { page_size: 100 } }).then((r) => setList(r.data.results || r.data)).catch(() => setList([]));
  };
  useEffect(() => { load(); }, [superuser]); // eslint-disable-line react-hooks/exhaustive-deps

  function switchTo(slug) {
    // Always send the slug. Blanking it for "default" meant a superuser whose
    // own workspace was something else silently stayed where they were.
    chooseWorkspace(slug);
    window.location.assign("/");
  }

  async function create(e) {
    e.preventDefault();
    if (!name.trim()) return;
    setBusy(true);
    setMsg(null);
    try {
      const { data } = await api.post("/workspaces/", { name: name.trim(), with_frameworks: withFrameworks });
      setName("");
      setMsg({ ok: true, text: `Workspace “${data.name}” created${withFrameworks ? " with the framework library" : ""}. Switch to it to add its people.` });
      load();
    } catch (err) {
      setMsg({ ok: false, text: errorText(err, "Couldn't create the workspace.") });
    } finally {
      setBusy(false);
    }
  }

  async function archive(ws) {
    if (!window.confirm(`Archive “${ws.name}”? Its people can no longer sign in and it drops out of every scheduled job. Nothing is deleted.`)) return;
    setBusy(true);
    setMsg(null);
    try {
      await api.patch(`/workspaces/${ws.id}/`, { is_active: false });
      setMsg({ ok: true, text: `“${ws.name}” archived.` });
      load();
    } catch (err) {
      setMsg({ ok: false, text: errorText(err, "Couldn't archive the workspace.") });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mt-6 border-t border-line pt-5" data-testid="workspaces">
      <Label as="p" className="mb-2.5">Workspace</Label>
      <p className="text-[13px] text-ink">
        {current ? (
          <>
            <span className="font-semibold">{current.name}</span>
            <span className="ml-2 font-mono text-xs text-muted">{current.slug}</span>
          </>
        ) : "…"}
      </p>
      <p className="mt-1.5 max-w-[62ch] text-xs leading-snug text-muted">
        Everything you see — frameworks, documents, risks, vendors, packages, people — belongs to this workspace. Other organisations on the same installation see only their own.
      </p>
      {superuser ? (
        <>
          <ul className="mt-4 divide-y divide-line rounded-xl border border-line bg-surface-2">
            {(list || []).map((ws) => (
              <li key={ws.id} className="flex flex-wrap items-center gap-2 px-3 py-2 text-[13px]">
                <span className={cn("font-medium", ws.is_active ? "text-ink" : "text-faint line-through")}>{ws.name}</span>
                <span className="font-mono text-xs text-muted">{ws.slug}</span>
                <span className="text-xs text-muted">· {ws.users} {ws.users === 1 ? "person" : "people"}</span>
                <span className="ml-auto flex items-center gap-1.5">
                  {current?.id === ws.id ? (
                    <Badge tone="accent">current</Badge>
                  ) : ws.is_active ? (
                    <Button size="sm" variant="secondary" onClick={() => switchTo(ws.slug)} disabled={busy}>Switch</Button>
                  ) : (
                    <Badge tone="muted">archived</Badge>
                  )}
                  {ws.is_active && ws.slug !== "default" && current?.id !== ws.id ? (
                    <Button size="sm" variant="ghost" onClick={() => archive(ws)} disabled={busy}>Archive</Button>
                  ) : null}
                </span>
              </li>
            ))}
            {list && !list.length ? <li className="px-3 py-2 text-xs text-muted">No workspaces.</li> : null}
          </ul>
          <form onSubmit={create} className="mt-3 flex flex-wrap items-end gap-2">
            <Field id="new-workspace" label="New workspace" className="min-w-[220px] flex-1">
              <input id="new-workspace" className="input" value={name} onChange={(e) => setName(e.target.value)} placeholder="Organisation name" disabled={busy} />
            </Field>
            <label className="flex items-center gap-2 pb-2 text-xs text-muted">
              <input type="checkbox" checked={withFrameworks} onChange={(e) => setWithFrameworks(e.target.checked)} disabled={busy} />
              Seed the framework library
            </label>
            <Button type="submit" size="sm" disabled={busy || !name.trim()}>{busy ? "Working…" : "Create"}</Button>
          </form>
          <p className="mt-2 text-xs text-muted">Switching reloads the app in that workspace; sign out to come back to your own.</p>
        </>
      ) : null}
      {msg ? <Notice msg={msg} className="mt-3" /> : null}
    </div>
  );
}

/* ---------- About ---------- */

function AboutSection() {
  const { health } = useShell();
  const [frameworks, setFrameworks] = useState(null);
  const [err, setErr] = useState(null);

  useEffect(() => {
    let alive = true;
    fetchAll("/frameworks/")
      .then((list) => {
        if (alive) setFrameworks(list);
      })
      .catch((e) => {
        if (!alive) return;
        setErr(errorText(e, "Couldn't load frameworks."));
        setFrameworks([]);
      });
    return () => {
      alive = false;
    };
  }, []);

  const scanning = health?.scanning;
  const scannerLabel = !scanning || !scanning.enabled
    ? "Off"
    : scanning.reachable
      ? `On · answering${scanning.latency_ms != null ? ` in ${scanning.latency_ms} ms` : ""}`
      : `On · UNREACHABLE${scanning.down_since ? ` since ${String(scanning.down_since).slice(0, 16).replace("T", " ")}` : ""}`;
  const rows = [
    ["Version", health?.version ? `v${health.version}` : "—"],
    ["Frameworks", frameworks ? `${frameworks.length} loaded` : "…"],
    ["Data", health?.demo_accounts ? "Seeded demo set" : "Live workspace"],
    ["Malware scanning", scannerLabel],
    ["Package signing", health?.signing?.key_id
      ? `Ed25519 · key ${health.signing.key_id}`
      : health?.signing?.enabled === false ? "Off" : "No key configured"],
    ...(health?.signing?.fingerprint ? [["Signing key fingerprint", `sha256:${health.signing.fingerprint}`]] : []),
    ["Licence", "MIT"],
  ];

  return (
    <Panel className="p-5">
      <SectionTitle
        title="About"
        badge={
          health?.demo_accounts ? (
            <Badge tone="warning" mono>
              Demo data
            </Badge>
          ) : null
        }
      >
        Conformiti tracks control implementation, document lifecycle and risk treatment against the frameworks loaded in this workspace.
        Self-hosted, with role-based access and folder-level permissions inherited down the tree.
      </SectionTitle>

      <dl className="mt-5 grid max-w-[560px] grid-cols-1 gap-3 sm:grid-cols-2">
        {rows.map(([k, v]) => (
          <div key={k} className="flex justify-between gap-4 border-b border-line pb-2">
            <dt className="text-xs text-muted">{k}</dt>
            <dd className="tabular font-mono text-xs text-ink">{v}</dd>
          </div>
        ))}
      </dl>

      <Label as="p" className="mb-2.5 mt-6">Frameworks</Label>
      {err ? (
        <div className="notice notice-err max-w-[640px]" role="alert">
          {err}
        </div>
      ) : frameworks === null ? (
        <Loading className="py-6 text-left" />
      ) : frameworks.length === 0 ? (
        <Empty title="No frameworks loaded">An administrator can load a framework to start tracking controls.</Empty>
      ) : (
        <ul className="max-w-[640px] divide-y divide-line rounded-xl border border-line">
          {frameworks.map((f) => (
            <li key={f.key || f.id} className="flex flex-wrap items-center gap-x-4 gap-y-1 px-4 py-2.5">
              <span className="min-w-0 flex-1">
                <span className="block text-[13px] font-medium text-ink">{f.name}</span>
                {f.authority ? <span className="block text-xs text-muted">{f.authority}</span> : null}
              </span>
              {f.version ? (
                <Badge tone="muted" mono>
                  {f.version}
                </Badge>
              ) : null}
              {typeof f.control_count === "number" ? (
                <span className="tabular font-mono text-2xs text-faint">{f.control_count} controls</span>
              ) : null}
            </li>
          ))}
        </ul>
      )}

      <div className="mt-6 flex flex-wrap items-center gap-x-3 gap-y-1">
        <a href={DOCS_URL} target="_blank" rel="noreferrer" className="link">
          Documentation &amp; source
          <ExternalLinkIcon className="h-3 w-3" strokeWidth={2} aria-hidden="true" />
        </a>
        <span className="text-xs text-muted">Released under the MIT licence.</span>
      </div>
    </Panel>
  );
}

/* ---------- Page ---------- */

export default function Account({ me, onUpdate }) {
  const [section, setSection] = useState("profile");
  const initial = (me?.full_name || me?.username || "?").trim().slice(0, 1).toUpperCase() || "?";

  return (
    <PanelTransition>
      <Stack className="grid grid-cols-12 gap-4">
        <StackItem className="col-span-12 lg:col-span-3">
          <Panel as="aside" className="overflow-hidden">
            <div className="flex items-center gap-3 border-b border-line px-4 py-4">
              <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-accent text-[15px] font-semibold text-accent-ink" aria-hidden="true">
                {initial}
              </span>
              <span className="min-w-0">
                <span className="block truncate text-[13px] font-semibold text-ink">{me?.full_name || me?.username || "…"}</span>
                <span className="block truncate text-xs text-muted">{me?.role_detail?.name || "No role"}</span>
              </span>
            </div>
            <nav aria-label="Settings sections">
              <ul className="p-2">
                {SECTIONS.map((s) => {
                  const on = s.id === section;
                  const Icon = s.icon;
                  return (
                    <li key={s.id}>
                      <button
                        type="button"
                        onClick={() => setSection(s.id)}
                        aria-current={on || undefined}
                        className={cn(
                          "relative flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-left transition-colors duration-150 ease-out",
                          on ? "text-accent" : "text-muted hover:bg-surface-2 hover:text-ink"
                        )}
                      >
                        {on ? (
                          <motion.span
                            layoutId="settings-active"
                            className="absolute inset-0 rounded-lg bg-accent/10"
                            transition={{ type: "spring", stiffness: 520, damping: 38 }}
                            aria-hidden="true"
                          />
                        ) : null}
                        <Icon className="relative h-4 w-4 shrink-0" strokeWidth={1.75} aria-hidden="true" />
                        <span className="relative text-[13px] font-medium">{s.label}</span>
                      </button>
                    </li>
                  );
                })}
              </ul>
            </nav>
          </Panel>
        </StackItem>

        <StackItem className="col-span-12 lg:col-span-9">
          <AnimatePresence mode="wait">
            <motion.div
              key={section}
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -6 }}
              transition={{ duration: 0.22, ease: EASE }}
            >
              {section === "profile" ? <ProfileSection me={me} onUpdate={onUpdate} /> : null}
              {section === "appearance" ? <AppearanceSection /> : null}
              {section === "security" ? <SecuritySection /> : null}
              {section === "notifications" ? <NotificationsSection me={me} onUpdate={onUpdate} onGoProfile={() => setSection("profile")} /> : null}
              {section === "access" ? <AccessSection me={me} /> : null}
              {section === "about" ? <AboutSection /> : null}
            </motion.div>
          </AnimatePresence>
        </StackItem>
      </Stack>
    </PanelTransition>
  );
}
