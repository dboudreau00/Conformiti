import { Button } from "../ui/Button.jsx";
import { Label, Panel, PanelHeader } from "../ui/Panel.jsx";

export const PASSWORD_MIN = 12;

export const BLANK_USER_FORM = { username: "", first: "", last: "", email: "", job: "", role: "", password: "" };

/** Inline "New user" panel. Controlled: the page owns the form state so a
 * successful create can reset it and collapse the panel. */
export function NewUserForm({ id, form, onChange, roles, onSubmit, onCancel, busy, error }) {
  const set = (k) => (e) => onChange({ ...form, [k]: e.target.value });
  const valid = form.username.trim() && form.role && form.password.length >= PASSWORD_MIN;

  return (
    <Panel as="div" id={id}>
      <PanelHeader title="New user">
        <Label>Password required · share it securely</Label>
      </PanelHeader>
      <form onSubmit={onSubmit} className="grid grid-cols-1 gap-4 p-5 md:grid-cols-3">
        <div>
          <label htmlFor="nu-username" className="field-label">Username *</label>
          <input id="nu-username" className="input font-mono" autoComplete="off" required value={form.username} onChange={set("username")} />
        </div>
        <div>
          <label htmlFor="nu-first" className="field-label">First name</label>
          <input id="nu-first" className="input" autoComplete="off" value={form.first} onChange={set("first")} />
        </div>
        <div>
          <label htmlFor="nu-last" className="field-label">Last name</label>
          <input id="nu-last" className="input" autoComplete="off" value={form.last} onChange={set("last")} />
        </div>
        <div>
          <label htmlFor="nu-email" className="field-label">Email</label>
          <input id="nu-email" type="email" className="input" autoComplete="off" value={form.email} onChange={set("email")} />
        </div>
        <div>
          <label htmlFor="nu-job" className="field-label">Job title</label>
          <input id="nu-job" className="input" autoComplete="off" value={form.job} onChange={set("job")} />
        </div>
        <div>
          <label htmlFor="nu-role" className="field-label">Role *</label>
          <select id="nu-role" className="input" required value={form.role} onChange={set("role")}>
            <option value="" disabled>Choose a role</option>
            {roles.map((r) => (
              <option key={r.id} value={r.id}>{r.name}</option>
            ))}
          </select>
        </div>
        <div className="md:col-span-2">
          <label htmlFor="nu-password" className="field-label">Temporary password *</label>
          <input
            id="nu-password"
            type="password"
            className="input"
            autoComplete="new-password"
            required
            minLength={PASSWORD_MIN}
            value={form.password}
            onChange={set("password")}
          />
          <p className="mt-1.5 text-2xs text-faint">
            At least {PASSWORD_MIN} characters. The user should change it after their first sign-in.
          </p>
        </div>
        <div className="flex items-end gap-2 md:justify-end">
          <Button type="button" variant="ghost" onClick={onCancel} disabled={busy}>
            Cancel
          </Button>
          <Button type="submit" variant="primary" disabled={busy || !valid}>
            {busy ? "Creating…" : "Create user"}
          </Button>
        </div>
        {error ? (
          <div className="notice notice-err md:col-span-3" role="alert">{error}</div>
        ) : null}
      </form>
    </Panel>
  );
}
