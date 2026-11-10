import { useEffect, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { PlusIcon, SearchIcon } from "lucide-react";
import api, { fetchAll, passwordMinLength } from "../api/client.js";
import { Badge } from "../components/ui/Badge.jsx";
import { Button } from "../components/ui/Button.jsx";
import { useConfirm } from "../components/ui/Dialog.jsx";
import { Notice } from "../components/ui/Notice.jsx";
import { Empty, Label, LoadError, Loading, Panel, PanelHeader } from "../components/ui/Panel.jsx";
import { usePage } from "../components/ui/ShowMore.jsx";
import { StatCard } from "../components/ui/StatCard.jsx";
import { Collapse, EASE, PanelTransition, Stack, StackItem } from "../components/layout/PanelTransition.jsx";
import { BLANK_USER_FORM, NewUserForm } from "../components/users/NewUserForm.jsx";
import { cn } from "../utils/cn.js";
import { errorText, loadFailReason } from "../utils/a11y.js";
import { useDeepLink } from "../utils/deepLink.js";
import { fmtDate } from "../utils/format.js";

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
  { id: "mfa", label: "Two-factor", className: "w-[110px]" },
  { id: "actions", label: "", className: "w-[340px]" },
];

const ROLE_COLS = [
  { id: "role", label: "Role", className: "w-[220px]" },
  { id: "desc", label: "Description" },
  { id: "caps", label: "Capabilities", className: "w-[340px]" },
];

// Labels match the create-user form so a rejected field reads as it did under its input. The blank ones are not fields
// (DRF's form-wide errors, a refused request's "detail"), so their message reads without a label.
const FIELD_LABELS = {
  username: "Username",
  email: "Email",
  password: "Temporary password",
  role: "Role",
  first_name: "First name",
  last_name: "Last name",
  job_title: "Job title",
  non_field_errors: "",
  detail: "",
};

// API field name to the create form's own key: a refusal for one of these is shown under its input.
const FORM_FIELDS = {
  username: "username",
  email: "email",
  password: "password",
  role: "role",
  first_name: "first",
  last_name: "last",
  job_title: "job",
};

// A key the form does not show is spelled out from its own letters, never printed as the API names it.
const fieldWords = (key) => {
  const words = String(key).replace(/_/g, " ").trim();
  return `${words.charAt(0).toUpperCase()}${words.slice(1)}`;
};

const cell = "px-5 py-3 align-middle";
// relative contains the sr-only header text: with no positioned ancestor it escapes the scroll wrapper and stretches the page.
const headCell = "table-head relative px-5 py-2 text-left font-normal";

export default function Users({ me }) {
  const { ask, confirmDialog } = useConfirm();
  const [users, setUsers] = useState([]);
  const [roles, setRoles] = useState([]);
  const [loading, setLoading] = useState(true);
  const [denied, setDenied] = useState(false);
  // A failed list is not an empty one: { reason } while the last load of each list failed, else null.
  const [loadFailed, setLoadFailed] = useState(null);
  const [rolesLoading, setRolesLoading] = useState(true);
  const [rolesErr, setRolesErr] = useState(null);
  const [showNew, setShowNew] = useState(false);
  const [banner, setBanner] = useState(null);
  const [pwFor, setPwFor] = useState(null);
  const [pwValue, setPwValue] = useState("");
  const [busyId, setBusyId] = useState(null);
  const [form, setForm] = useState(BLANK_USER_FORM);
  const [formErr, setFormErr] = useState(null);
  const [fieldErrs, setFieldErrs] = useState({});
  const [creating, setCreating] = useState(false);
  const [query, setQuery] = useState("");
  const needle = query.trim().toLowerCase();
  const shown = needle
    ? users.filter((u) => [u.username, u.full_name, u.email, u.job_title].some((v) => v && String(v).toLowerCase().includes(needle)))
    : users;
  const page = usePage(shown, 100, [needle]);

  const isAdmin = !!me?.capabilities?.manage_users;

  async function loadUsers() {
    setLoading(true);
    setLoadFailed(null);
    try {
      setUsers(await fetchAll("/users/"));
    } catch (e) {
      if (e?.response?.status === 403) setDenied(true);
      else {
        // Rows from before a failed refresh would describe accounts that may have changed, so none are kept.
        setUsers([]);
        setLoadFailed({ reason: loadFailReason(e) });
      }
    } finally {
      setLoading(false);
    }
  }

  function loadRoles() {
    setRolesLoading(true);
    setRolesErr(null);
    return api
      .get("/roles/")
      .then((r) => setRoles(r.data.results || r.data))
      .catch((e) => {
        if (e?.response?.status !== 403) setRolesErr({ reason: loadFailReason(e) });
      })
      .finally(() => setRolesLoading(false));
  }

  useEffect(() => {
    loadUsers();
    loadRoles();
  }, []);

  // The search box links here as ?search=<username>.
  useDeepLink((params) => {
    const text = params.get("search");
    if (text !== null) setQuery(text);
  });

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
      fail(e, "Couldn't update the user.");
    } finally {
      setBusyId(null);
    }
  }

  function toggleActive(u) {
    if (!u.is_active) {
      patchUser(u, { is_active: true }, `${u.username} activated.`);
      return;
    }
    ask({
      title: `Deactivate ${u.username}?`,
      description: "They are signed out and cannot sign in until the account is activated again. Their history is kept.",
      confirmLabel: "Deactivate user",
      onConfirm: () => patchUser(u, { is_active: false }, `${u.username} deactivated.`),
    });
  }

  function removeUser(u) {
    ask({
      title: `Delete ${u.username}?`,
      description: "This cannot be undone. Deactivating keeps their history and stops them signing in.",
      confirmLabel: "Delete user",
      onConfirm: async () => {
        setBusyId(u.id);
        try {
          await api.delete(`/users/${u.id}/`);
          ok(`Deleted ${u.username}.`);
          await loadUsers();
        } catch (e) {
          fail(e, "Couldn't delete the user.");
        } finally {
          setBusyId(null);
        }
      },
    });
  }

  async function savePassword(u) {
    if (pwValue.length < passwordMinLength()) return;
    setBusyId(u.id);
    try {
      await api.patch(`/users/${u.id}/`, { password: pwValue });
      ok(`Password set for ${u.username}. Their sessions are signed out.`);
      setPwFor(null);
      setPwValue("");
    } catch (e) {
      setBanner({ kind: "err", text: errorText(e, "Couldn't set the password.", { password: "New password" }) });
    } finally {
      setBusyId(null);
    }
  }

  function resetMfa(u) {
    ask({
      title: `Reset two-factor for ${u.username}?`,
      description: "Their two-factor setup and backup codes stop working. They set it up again the next time they sign in.",
      confirmLabel: "Reset two-factor",
      onConfirm: async () => {
        setBusyId(u.id);
        try {
          await api.post(`/users/${u.id}/reset_mfa/`);
          ok(`Two-factor reset for ${u.username}.`);
          await loadUsers();
        } catch (e) {
          fail(e, "Couldn't reset two-factor.");
        } finally {
          setBusyId(null);
        }
      },
    });
  }

  async function createUser(e) {
    e.preventDefault();
    setFormErr(null);
    setFieldErrs({});
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
      const r = err?.response;
      const d = r?.data;
      // A refused field reads under its own input; anything else reads once below the form. A throttle, a server fault
      // or a page of markup reads as errorText says it.
      const byField = r && r.status < 500 && r.status !== 429 && d && typeof d === "object" && !Array.isArray(d);
      const entries = byField ? Object.entries(d).filter(([k]) => k !== "code") : [];
      const onField = {};
      for (const [k, v] of entries) {
        if (FORM_FIELDS[k]) onField[FORM_FIELDS[k]] = [].concat(v).join(" ");
      }
      const lines = entries
        .filter(([k]) => !FORM_FIELDS[k])
        .map(([k, v]) => {
          const label = FIELD_LABELS[k] ?? fieldWords(k);
          return `${label ? `${label}: ` : ""}${[].concat(v).join(" ")}`;
        })
        .join(" ");
      setFieldErrs(onField);
      setFormErr(lines || (Object.keys(onField).length ? null : errorText(err, "Couldn't create the user.")));
    } finally {
      setCreating(false);
    }
  }

  function toggleNew() {
    setShowNew((v) => !v);
    setFormErr(null);
    setFieldErrs({});
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
          <Empty title="User management is restricted" />
        </Panel>
      </PanelTransition>
    );
  }

  const total = users.length;
  const unknown = loading || !!loadFailed;
  const active = users.filter((u) => u.is_active).length;
  const superusers = users.filter((u) => u.is_superuser).length;
  const mfaOn = users.filter((u) => u.mfa_enabled).length;

  return (
    <PanelTransition>
      {confirmDialog}
      <Stack className="flex flex-col gap-4">
        <StackItem className="grid grid-cols-1 gap-4 sm:grid-cols-3">
          <StatCard
            label="Users"
            value={unknown ? "-" : total}
            detail={loading ? "Loading…" : unknown ? undefined : `${active} active · ${total - active} inactive`}
          />
          <StatCard
            label="Superusers"
            value={unknown ? "-" : superusers}
          />
          <StatCard
            label="Two-factor"
            value={unknown ? "-" : mfaOn}
            suffix={unknown ? undefined : `/ ${total}`}
            tone={!unknown && total > 0 && mfaOn < total ? "warning" : undefined}
          />
        </StackItem>

        {banner ? (
          <StackItem>
            <Notice kind={banner.kind} onDismiss={() => setBanner(null)}>{banner.text}</Notice>
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
                    fieldErrors={fieldErrs}
                    rolesFailed={!!rolesErr}
                    onRetryRoles={loadRoles}
                  />
                </div>
              </Collapse>
            ) : null}
          </AnimatePresence>

          <Panel className="overflow-hidden">
            {/* The page heading already says "Users"; this row holds only the action. */}
            <PanelHeader>
              <Button
                size="sm"
                variant={showNew ? "secondary" : "primary"}
                aria-expanded={showNew}
                aria-controls={showNew ? "new-user-panel" : undefined}
                onClick={toggleNew}
                icon={<PlusIcon className="h-3.5 w-3.5" strokeWidth={2.25} aria-hidden="true" />}
              >
                New user
              </Button>
            </PanelHeader>
            {users.length > 0 ? (
              <div className="flex flex-wrap items-center gap-2 border-b border-line bg-surface-2 px-5 py-2.5">
                <div className="relative min-w-[240px] flex-1">
                  <SearchIcon
                    className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-faint"
                    strokeWidth={2}
                    aria-hidden="true"
                  />
                  <input
                    type="search"
                    className="input input-sm pl-8"
                    value={query}
                    placeholder="Search by username, name, email or job title"
                    aria-label="Search users"
                    onChange={(e) => setQuery(e.target.value)}
                  />
                </div>
                {needle ? <Label role="status">{shown.length} of {total} shown</Label> : null}
                {query ? (
                  <Button size="sm" variant="ghost" onClick={() => setQuery("")}>Clear</Button>
                ) : null}
              </div>
            ) : null}
            {loading ? (
              <Loading>Loading users…</Loading>
            ) : loadFailed ? (
              <LoadError what="The user list" reason={loadFailed.reason} onRetry={loadUsers} />
            ) : users.length === 0 ? (
              <Empty title="No users yet" />
            ) : shown.length === 0 ? (
              <Empty
                title="No users match"
                action={<Button size="sm" variant="secondary" onClick={() => setQuery("")}>Clear search</Button>}
              />
            ) : (
              <>
              <div className="overflow-x-auto" role="region" aria-label="Users" tabIndex={0}>
                <table className="w-full min-w-[1110px] border-collapse text-[13px]">
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
                    {page.visible.map((u, i) => (
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
                        onPwOpen={() => {
                          setPwFor(u.id);
                          setPwValue("");
                        }}
                        onPwClose={() => {
                          setPwFor(null);
                          setPwValue("");
                        }}
                        onPwSave={() => savePassword(u)}
                        onRole={(role) => patchUser(u, { role }, `Role updated for ${u.username}.`)}
                        onToggleActive={() => toggleActive(u)}
                        onResetMfa={() => resetMfa(u)}
                        onDelete={() => removeUser(u)}
                      />
                    ))}
                  </tbody>
                </table>
              </div>
              {page.remaining ? (
                <div className="border-t border-line px-5 py-3 text-center">
                  <Button size="sm" variant="secondary" onClick={page.more}>
                    Show {Math.min(page.size, page.remaining)} more of {page.remaining.toLocaleString()}
                  </Button>
                </div>
              ) : null}
              </>
            )}
          </Panel>
        </StackItem>

        <StackItem>
          <Panel className="overflow-hidden">
            <PanelHeader title="Roles & permissions" />
            {rolesLoading ? (
              <Loading>Loading roles…</Loading>
            ) : rolesErr ? (
              <LoadError what="Roles" reason={rolesErr.reason} onRetry={loadRoles} />
            ) : roles.length === 0 ? (
              <Empty title="No roles defined" />
            ) : (
              <div className="overflow-x-auto" role="region" aria-label="Roles and permissions" tabIndex={0}>
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
                          <td className={cn(cell, "py-2.5 text-xs text-muted")}>{r.description || "-"}</td>
                          <td className={cn(cell, "py-2.5")}>
                            {caps.length ? (
                              <span className="flex flex-wrap gap-1.5">
                                {caps.map(([k, label]) => (
                                  <Badge key={k} tone="accent" mono>{label}</Badge>
                                ))}
                              </span>
                            ) : (
                              <span className="text-xs text-faint">Read-only</span>
                            )}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
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
  const pwMin = passwordMinLength();
  const pwValid = pwValue.length >= pwMin;
  // A disabled control takes no focus, so the reason is text beside it, not a tooltip.
  const roleHint = self
    ? "Ask another administrator to change your role."
    : !touchable
      ? "Only an administrator who works across workspaces can change this account."
      : undefined;
  const hintId = `role-hint-${u.id}`;

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
              {self ? <Badge tone="accent" dot>You</Badge> : null}
            </span>
            <span className="block truncate text-xs text-muted">
              {u.full_name || "-"}
              {u.email ? ` · ${u.email}` : ""}
            </span>
          </span>
        </div>
      </td>
      <td className={cn(cell, "text-xs", u.job_title ? "text-ink" : "text-faint")}>{u.job_title || "-"}</td>
      <td className={cell}>
        <select
          className="input input-sm"
          aria-label={`Role for ${u.username}`}
          value={u.role || ""}
          disabled={self || !touchable || busy}
          aria-describedby={roleHint ? hintId : undefined}
          onChange={(e) => onRole(e.target.value)}
        >
          {/* A new account needs a role, so none is offered to pick; one that has none (its role was deleted) still reads true. */}
          {!u.role ? <option value="" disabled>No role</option> : null}
          {/* Until the roles arrive (or fail) the current role is not among the options, and a select whose value matches
              none shows the first one. */}
          {u.role && !roles.some((r) => r.id === u.role) ? (
            <option value={u.role}>{u.role_detail?.name || "Current role"}</option>
          ) : null}
          {roles.map((r) => (
            <option key={r.id} value={r.id}>{r.name}</option>
          ))}
        </select>
        {roleHint ? <span id={hintId} className="mt-1 block text-2xs text-faint">{roleHint}</span> : null}
      </td>
      <td className={cn(cell, "tabular font-mono text-xs text-muted")}>{u.last_login ? fmtDate(u.last_login) : "Never"}</td>
      <td className={cell}>
        <Badge tone={u.is_active ? "success" : "faint"} dot>{u.is_active ? "Active" : "Inactive"}</Badge>
      </td>
      <td className={cell}>
        <Badge tone={u.mfa_enabled ? "success" : "faint"} dot={u.mfa_enabled}>{u.mfa_enabled ? "On" : "Off"}</Badge>
      </td>
      <td className={cn(cell, "text-right")}>
        {pwOpen ? (
          <div className="flex items-center justify-end gap-2">
            <input
              type="password"
              className="input input-sm w-[170px] font-mono"
              aria-label={`New password for ${u.username}`}
              placeholder={`New password (${pwMin}+ chars)`}
              autoComplete="new-password"
              autoFocus
              minLength={pwMin}
              value={pwValue}
              onChange={(e) => onPwChange(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  if (pwValid && !busy) onPwSave();
                }
                if (e.key === "Escape") {
                  e.preventDefault();
                  onPwClose();
                }
              }}
            />
            <Button size="sm" variant="primary" disabled={!pwValid || busy} onClick={onPwSave}>
              {busy ? "Saving…" : "Save changes"}
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
              <Button size="sm" variant="ghost" disabled={busy} onClick={onResetMfa}>Reset two-factor</Button>
            ) : null}
            {touchable && !self && !u.is_superuser ? (
              <Button
                size="sm"
                variant="ghost"
                className="text-danger hover:bg-danger/10 hover:text-danger"
                disabled={busy}
                onClick={onDelete}
              >
                Delete
              </Button>
            ) : null}
          </div>
        )}
      </td>
    </motion.tr>
  );
}
