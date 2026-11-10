import { passwordMinLength } from "../../api/client.js";
import { Button } from "../ui/Button.jsx";
import { Notice } from "../ui/Notice.jsx";
import { Panel, PanelHeader } from "../ui/Panel.jsx";

export const BLANK_USER_FORM = { username: "", first: "", last: "", email: "", job: "", role: "", password: "" };

function FieldError({ id, text }) {
  return text ? <p id={id} className="mt-1.5 text-xs text-danger" role="alert">{text}</p> : null;
}

export function NewUserForm({
  id, form, onChange, roles, onSubmit, onCancel, busy, error, fieldErrors = {}, rolesFailed, onRetryRoles,
}) {
  const set = (k) => (e) => onChange({ ...form, [k]: e.target.value });
  // What the server refused on a field, tied to its input.
  const bad = (k) => (fieldErrors[k] ? { "aria-invalid": true, "aria-describedby": `nu-${k}-error` } : {});
  const minLength = passwordMinLength();
  const valid = form.username.trim() && form.role && form.password.length >= minLength;

  return (
    <Panel as="div" id={id}>
      <PanelHeader title="New user" />
      <form onSubmit={onSubmit} className="grid grid-cols-1 gap-4 p-5 md:grid-cols-3">
        <div>
          <label htmlFor="nu-username" className="field-label">Username *</label>
          <input
            id="nu-username"
            className="input font-mono"
            autoComplete="off"
            required
            value={form.username}
            onChange={set("username")}
            {...bad("username")}
          />
          <FieldError id="nu-username-error" text={fieldErrors.username} />
        </div>
        <div>
          <label htmlFor="nu-first" className="field-label">First name</label>
          <input id="nu-first" className="input" autoComplete="off" value={form.first} onChange={set("first")} {...bad("first")} />
          <FieldError id="nu-first-error" text={fieldErrors.first} />
        </div>
        <div>
          <label htmlFor="nu-last" className="field-label">Last name</label>
          <input id="nu-last" className="input" autoComplete="off" value={form.last} onChange={set("last")} {...bad("last")} />
          <FieldError id="nu-last-error" text={fieldErrors.last} />
        </div>
        <div>
          <label htmlFor="nu-email" className="field-label">Email</label>
          <input id="nu-email" type="email" className="input" autoComplete="off" value={form.email} onChange={set("email")} {...bad("email")} />
          <FieldError id="nu-email-error" text={fieldErrors.email} />
        </div>
        <div>
          <label htmlFor="nu-job" className="field-label">Job title</label>
          <input id="nu-job" className="input" autoComplete="off" value={form.job} onChange={set("job")} {...bad("job")} />
          <FieldError id="nu-job-error" text={fieldErrors.job} />
        </div>
        <div>
          <label htmlFor="nu-role" className="field-label">Role *</label>
          <select
            id="nu-role"
            className="input"
            required
            value={form.role}
            onChange={set("role")}
            aria-invalid={fieldErrors.role ? true : undefined}
            aria-describedby={rolesFailed ? "nu-role-error" : fieldErrors.role ? "nu-role-refused" : undefined}
          >
            <option value="" disabled>Choose a role</option>
            {roles.map((r) => (
              <option key={r.id} value={r.id}>{r.name}</option>
            ))}
          </select>
          {rolesFailed ? (
            <p id="nu-role-error" className="mt-1.5 text-xs text-danger" role="alert">
              Roles could not be loaded.{" "}
              <button type="button" className="link" onClick={onRetryRoles}>Try again</button>
            </p>
          ) : null}
          <FieldError id="nu-role-refused" text={fieldErrors.role} />
        </div>
        <div className="md:col-span-2">
          <label htmlFor="nu-password" className="field-label">Temporary password *</label>
          <input
            id="nu-password"
            type="password"
            className="input"
            autoComplete="new-password"
            required
            minLength={minLength}
            value={form.password}
            onChange={set("password")}
            {...bad("password")}
          />
          {fieldErrors.password ? (
            <FieldError id="nu-password-error" text={fieldErrors.password} />
          ) : (
            <p className="mt-1.5 text-2xs text-faint">
              At least {minLength} characters.
            </p>
          )}
        </div>
        <div className="flex items-end gap-2 md:justify-end">
          <Button type="button" variant="ghost" onClick={onCancel} disabled={busy}>
            Cancel
          </Button>
          <Button type="submit" variant="primary" disabled={busy || !valid}>
            {busy ? "Creating…" : "Create user"}
          </Button>
        </div>
        {error ? <Notice kind="err" className="md:col-span-3">{error}</Notice> : null}
      </form>
    </Panel>
  );
}
