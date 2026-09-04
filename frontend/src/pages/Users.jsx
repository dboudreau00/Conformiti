import { useEffect, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { PlusIcon, XIcon } from "lucide-react";
import api, { fetchAll } from "../api/client.js";
import { Badge } from "../components/ui/Badge.jsx";
import { Button } from "../components/ui/Button.jsx";
import { Empty, Label, Loading, Panel, PanelHeader } from "../components/ui/Panel.jsx";
import { StatCard } from "../components/ui/StatCard.jsx";
import { Collapse, EASE, PanelTransition, Stack, StackItem } from "../components/layout/PanelTransition.jsx";
import { BLANK_USER_FORM, NewUserForm, PASSWORD_MIN } from "../components/users/NewUserForm.jsx";
import { cn } from "../utils/cn.js";
import { errorText } from "../utils/a11y.js";

const CAP_LABELS = [
  ["can_manage_users", "users"],
  ["can_manage_frameworks", "frameworks"],
  ["can_manage_documents", "documents"],
  ["can_manage_folders", "folders"],
  ["can_view_all", "view all"],
  ["is_auditor", "auditor"],
];

const USER_COLS = [
  { id: "user", label: "User" },
  { id: "job", label: "Job title", className: "w-[150px]" },
  { id: "role", label: "Role", className: "w-[190px]" },
  { id: "login", label: "Last login", className: "w-[115px]" },
  { id: "status", label: "Status", className: "w-[95px]" },
  { id: "mfa", label: "2FA", className: "w-[80px]" },
  { id: "actions", label: "", className: "w-[340px]" },
];

const ROLE_COLS = [
  { id: "role", label: "Role", className: "w-[220px]" },
  { id: "desc", label: "Description" },
  { id: "caps", label: "Capabilities", className: "w-[340px]" },
];

const cell = "px-5 py-3 align-middle";
const headCell = "table-head px-5 py-2 text-left font-normal";

export default function Users({ me }) {
  const [users, setUsers] = useState([]);
  const [roles, setRoles] = useState([]);
  const [loading, setLoading] = useState(true);
  const [denied, setDenied] = useState(false);
  const [rolesErr, setRolesErr] = useState(null);
  const [showNew, setShowNew] = useState(false);
  const [banner, setBanner] = useState(null); // {kind:"ok"|"err", text}
  const [pwFor, setPwFor] = useState(null); // user id with password editor open
  const [pwValue, setPwValue] = useState("");
  const [busyId, setBusyId] = useState(null); // user id with a request in flight
  const [form, setForm] = useState(BLANK_USER_FORM);
  const [formErr, setFormErr] = useState(null);
  const [creating, setCreating] = useState(false);

  const isAdmin = !!me?.capabilities?.manage_users;

  async function loadUsers() {
    setLoading(true);
    try {
      setUsers(await fetchAll("/users/"));
    } catch (e) {
      if (e?.response?.status === 403) setDenied(true);
      else setBanner({ kind: "err", text: errorText(e, "Couldn't load users.") });
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadUsers();
    api
      .get("/roles/")
      .then((r) => setRoles(r.data.results || r.data))
      .catch((e) => {
        if (e?.response?.status !== 403) setRolesErr(errorText(e, "Couldn't load roles."));
      });
  }, []);

  const ok = (text) => setBanner({ kind: "ok", text });
  const fail = (e, fallback) => setBanner({ kind: "err", text: errorText(e, fallback) });

  // Only a superuser may touch another superuser's account.
  const canTouch = (u) => !(u.is_superuser && !me?.is_superuser);

  async function patchUser(u, payload, doneMsg) {
    setBusyId(u.id);
    try {
      await api.patch(`/users/${u.id}/`, payload);
      if (doneMsg) ok(doneMsg);
      await loadUsers();
    } catch (e) {
      fail(e, "Update failed.");
    } finally {
      setBusyId(null);
    }
  }

  async function removeUser(u) {
    if (!window.confirm(`Delete ${u.username}? This cannot be undone. Deactivating is usually safer.`)) return;
    setBusyId(u.id);
    try {
      await api.delete(`/users/${u.id}/`);
      ok(`Deleted ${u.username}.`);
      await loadUsers();
    } catch (e) {
      fail(e, "Delete failed.");
    } finally {
      setBusyId(null);
    }
  }

  async function savePassword(u) {
    if (pwValue.length < PASSWORD_MIN) return;
    setBusyId(u.id);
    try {
      await api.patch(`/users/${u.id}/`, { password: pwValue });
      ok(`Password set for ${u.username}. Share it with them securely.`);
      setPwFor(null);
      setPwValue("");
    } catch (e) {
      fail(e, "Password rejected.");
    } finally {
      setBusyId(null);
    }
  }

  async function resetMfa(u) {
    if (!window.confirm(`Reset two-factor for ${u.username}? They'll need to set it up again on next sign-in.`)) return;
    setBusyId(u.id);
    try {
      await api.post(`/users/${u.id}/reset_mfa/`);
      ok(`MFA reset for ${u.username}.`);
      await loadUsers();
    } catch (e) {
      fail(e, "Couldn't reset MFA.");
    } finally {
      setBusyId(null);
    }
  }

  async function createUser(e) {
    e.preventDefault();
    setFormErr(null);
    const payload = {
      username: form.username.trim(),
      first_name: form.first.trim(),
      last_name: form.last.trim(),
      email: form.email.trim(),
      job_title: form.job.trim(),
      role: form.role || null,
      password: form.password,
      is_active: true,
    };
    setCreating(true);
    try {
      await api.post("/users/", payload);
      ok(`Created ${payload.username}.`);
      setShowNew(false);
      setForm(BLANK_USER_FORM);
      await loadUsers();
    } catch (err) {
      const d = err?.response?.data;
      setFormErr(
        d && typeof d === "object"
          ? Object.entries(d)
              .map(([k, v]) => `${k}: ${[].concat(v).join(" ")}`)
              .join(" · ")
          : errorText(err, "Could not create the user.")
      );
    } finally {
      setCreating(false);
    }
  }

  function toggleNew() {
    setShowNew((v) => !v);
    setFormErr(null);
  }

  if (!me) {
    return (
      <PanelTransition>
        <Loading />
      </PanelTransition>
    );
  }

  if (!isAdmin || denied) {
    return (
      <PanelTransition>
        <Panel>
          <Empty title="User management is restricted">
            User management needs the <b className="font-medium text-ink">manage users</b> capability (Administrator role).
            Ask an administrator for access.
          </Empty>
        </Panel>
      </PanelTransition>
    );
  }

  const total = users.length;
  const active = users.filter((u) => u.is_active).length;
  const superusers = users.filter((u) => u.is_superuser).length;
  const mfaOn = users.filter((u) => u.mfa_enabled).length;

  return (
    <PanelTransition>
      <Stack className="flex flex-col gap-4">
        <StackItem className="grid grid-cols-1 gap-4 sm:grid-cols-3">
          <StatCard
            label="Members"
            value={loading ? "—" : total}
            detail={loading ? "Loading…" : `${active} active · ${total - active} inactive`}
          />
          <StatCard
            label="Superusers"
            value={loading ? "—" : superusers}
            detail="Workspace-wide grants, managed only by superusers"
          />
          <StatCard
            label="Two-factor"
            value={loading ? "—" : mfaOn}
            suffix={loading ? undefined : `/ ${total}`}
            tone={!loading && total > 0 && mfaOn < total ? "warning" : undefined}
            detail="Accounts with an authenticator enrolled"
          />
        </StackItem>

        {banner ? (
          <StackItem>
            <div
              role={banner.kind === "err" ? "alert" : "status"}
              className={cn("notice flex items-center justify-between gap-3", banner.kind === "err" ? "notice-err" : "notice-ok")}
            >
              <span>{banner.text}</span>
              <button type="button" className="link shrink-0" onClick={() => setBanner(null)}>
                Dismiss
              </button>
            </div>
          </StackItem>
        ) : null}

        <StackItem>
          <AnimatePresence initial={false}>
            {showNew ? (
              <Collapse open key="new-user">
                <div className="pb-4">
                  <NewUserForm
                    id="new-user-panel"
                    form={form}
                    onChange={setForm}
                    roles={roles}
                    onSubmit={createUser}
                    onCancel={toggleNew}
                    busy={creating}
                    error={formErr}
                  />
                </div>
              </Collapse>
            ) : null}
          </AnimatePresence>

          <Panel className="overflow-hidden">
            <PanelHeader title="Users">
              <div className="flex items-center gap-3">
                <Label className="hidden sm:inline">{loading ? "Loading…" : `${active} active · ${total} total`}</Label>
                <Button
                  size="sm"
                  variant={showNew ? "secondary" : "primary"}
                  aria-expanded={showNew}
                  aria-controls={showNew ? "new-user-panel" : undefined}
                  onClick={toggleNew}
                  icon={
                    showNew ? (
                      <XIcon className="h-3.5 w-3.5" strokeWidth={2.25} aria-hidden="true" />
                    ) : (
                      <PlusIcon className="h-3.5 w-3.5" strokeWidth={2.25} aria-hidden="true" />
                    )
                  }
                >
                  {showNew ? "Cancel" : "New user"}
                </Button>
              </div>
            </PanelHeader>
            {loading ? (
              <Loading>Loading users…</Loading>
            ) : users.length === 0 ? (
              <Empty title="No users yet">Create the first account with New user.</Empty>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full min-w-[1080px] border-collapse text-[13px]">
                  <thead>
                    <tr className="border-b border-line bg-surface-2">
                      {USER_COLS.map((c) => (
                        <th key={c.id} scope="col" className={cn(headCell, c.className)}>
                          {c.label || <span className="sr-only">Actions</span>}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-line">
                    {users.map((u, i) => (
                      <UserRow
                        key={u.id}
                        index={i}
                        u={u}
                        me={me}
                        roles={roles}
                        touchable={canTouch(u)}
                        busy={busyId === u.id}
                        pwOpen={pwFor === u.id}
                        pwValue={pwValue}
                        onPwChange={setPwValue}
                        onPwOpen={() => { setPwFor(u.id); setPwValue(""); }}
                        onPwClose={() => { setPwFor(null); setPwValue(""); }}
                        onPwSave={() => savePassword(u)}
                        onRole={(role) => patchUser(u, { role }, `Role updated for ${u.username}.`)}
                        onToggleActive={() =>
                          patchUser(u, { is_active: !u.is_active }, `${u.username} ${u.is_active ? "deactivated" : "activated"}.`)
                        }
                        onResetMfa={() => resetMfa(u)}
                        onDelete={() => removeUser(u)}
                      />
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Panel>
        </StackItem>

        <StackItem>
          <Panel className="overflow-hidden">
            <PanelHeader title="Roles & permissions" meta="What each role can do" />
            {rolesErr ? (
              <div className="p-5">
                <div className="notice notice-err" role="alert">{rolesErr}</div>
              </div>
            ) : roles.length === 0 ? (
              <Empty title="No roles defined">Roles are seeded on first install.</Empty>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full min-w-[720px] border-collapse text-[13px]">
                  <thead>
                    <tr className="border-b border-line bg-surface-2">
                      {ROLE_COLS.map((c) => (
                        <th key={c.id} scope="col" className={cn(headCell, c.className)}>{c.label}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-line">
                    {roles.map((r) => {
                      const caps = CAP_LABELS.filter(([k]) => r[k]);
                      return (
                        <tr key={r.id} className="transition-colors duration-150 ease-out hover:bg-surface-2">
                          <td className={cn(cell, "py-2.5")}>
                            <span className="inline-flex flex-wrap items-center gap-2">
                              <span className="font-medium text-ink">{r.name}</span>
                              {r.is_system ? <Badge tone="faint" mono>built-in</Badge> : null}
                            </span>
                          </td>
                          <td className={cn(cell, "py-2.5 text-xs text-muted")}>{r.description || "—"}</td>
                          <td className={cn(cell, "py-2.5")}>
                            {caps.length ? (
                              <span className="flex flex-wrap gap-1.5">
                                {caps.map(([k, label]) => (
                                  <Badge key={k} tone="accent" mono>{label}</Badge>
                                ))}
                              </span>
                            ) : (
                              <span className="text-xs text-faint">read-only · folder grants apply</span>
                            )}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
            <p className="border-t border-line px-5 py-2.5 text-2xs text-faint">
              Folder-level access is granted per folder on the Documents page.
            </p>
          </Panel>
        </StackItem>
      </Stack>
    </PanelTransition>
  );
}

function UserRow({
  index, u, me, roles, touchable, busy,
  pwOpen, pwValue, onPwChange, onPwOpen, onPwClose, onPwSave,
  onRole, onToggleActive, onResetMfa, onDelete,
}) {
  const self = u.id === me?.id;
  const initial = (u.full_name || u.username || "?").trim().charAt(0).toUpperCase();
  const pwValid = pwValue.length >= PASSWORD_MIN;
  const roleHint = self
    ? "You cannot change your own role — ask another administrator."
    : !touchable
      ? "Only a superuser can modify a superuser account."
      : undefined;

  return (
    <motion.tr
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.22, ease: EASE, delay: Math.min(index, 12) * 0.03 }}
      className={cn("transition-colors duration-150 ease-out hover:bg-surface-2", busy && "opacity-70")}
      aria-busy={busy || undefined}
    >
      <td className={cell}>
        <div className="flex items-center gap-3">
          <span
            className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-accent/10 text-[13px] font-semibold text-accent"
            aria-hidden="true"
          >
            {initial}
          </span>
          <span className="min-w-0">
            <span className="flex flex-wrap items-center gap-2">
              <span className="font-mono text-[13px] font-medium text-ink">{u.username}</span>
              {u.is_superuser ? <Badge tone="faint" mono>superuser</Badge> : null}
              {self ? <Badge tone="accent" dot>you</Badge> : null}
            </span>
            <span className="block truncate text-xs text-muted">
              {u.full_name || "—"}
              {u.email ? ` · ${u.email}` : ""}
            </span>
          </span>
        </div>
      </td>
      <td className={cn(cell, "text-xs", u.job_title ? "text-ink" : "text-faint")}>{u.job_title || "—"}</td>
      <td className={cell}>
        <select
          className="input input-sm"
          aria-label={`Role for ${u.username}`}
          value={u.role || ""}
          disabled={self || !touchable || busy}
          title={roleHint}
          onChange={(e) => onRole(e.target.value || null)}
        >
          <option value="">No role</option>
          {roles.map((r) => (
            <option key={r.id} value={r.id}>{r.name}</option>
          ))}
        </select>
      </td>
      <td className={cn(cell, "tabular font-mono text-xs text-muted")}>{u.last_login ? u.last_login.slice(0, 10) : "never"}</td>
      <td className={cell}>
        <Badge tone={u.is_active ? "success" : "faint"} dot>{u.is_active ? "active" : "inactive"}</Badge>
      </td>
      <td className={cell}>
        <Badge tone={u.mfa_enabled ? "success" : "faint"} dot={u.mfa_enabled}>{u.mfa_enabled ? "on" : "off"}</Badge>
      </td>
      <td className={cn(cell, "text-right")}>
        {pwOpen ? (
          <div className="flex items-center justify-end gap-2">
            <input
              type="password"
              className="input input-sm w-[170px] font-mono"
              aria-label={`New password for ${u.username}`}
              placeholder={`New password (${PASSWORD_MIN}+ chars)`}
              autoComplete="new-password"
              autoFocus
              minLength={PASSWORD_MIN}
              value={pwValue}
              onChange={(e) => onPwChange(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") { e.preventDefault(); if (pwValid && !busy) onPwSave(); }
                if (e.key === "Escape") { e.preventDefault(); onPwClose(); }
              }}
            />
            <Button size="sm" variant="primary" disabled={!pwValid || busy} onClick={onPwSave}>
              {busy ? "Saving…" : "Save"}
            </Button>
            <Button size="sm" variant="ghost" disabled={busy} onClick={onPwClose}>Cancel</Button>
          </div>
        ) : (
          <div className="flex flex-wrap items-center justify-end gap-1">
            {touchable ? (
              <Button size="sm" variant="ghost" disabled={busy} onClick={onPwOpen}>Set password</Button>
            ) : null}
            {touchable && !self ? (
              <Button size="sm" variant="ghost" disabled={busy} onClick={onToggleActive}>
                {u.is_active ? "Deactivate" : "Activate"}
              </Button>
            ) : null}
            {touchable && u.mfa_enabled ? (
              <Button size="sm" variant="ghost" disabled={busy} onClick={onResetMfa}>Reset 2FA</Button>
            ) : null}
            {touchable && !self && !u.is_superuser ? (
              <Button size="sm" variant="ghost" className="text-danger hover:bg-danger/10 hover:text-danger" disabled={busy} onClick={onDelete}>
                Delete
              </Button>
            ) : null}
            {!touchable ? <span className="text-2xs text-faint">superuser only</span> : null}
          </div>
        )}
      </td>
    </motion.tr>
  );
}
