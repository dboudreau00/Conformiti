import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import axios from "axios";
import { login, oidcConfig, redeemSso } from "../api/client.js";
import { Button } from "../components/ui/Button.jsx";
import { Label, Panel } from "../components/ui/Panel.jsx";

// What the server's sso_error codes mean to a person. Anything unlisted is a
// plain refusal; the audit log has the specifics.
const SSO_ERRORS = {
  disabled: "Single sign-on is not configured on this server.",
  state: "That sign-in link expired or was already used. Start again.",
  provider: "The identity provider could not be reached. Try again in a moment.",
  token: "The identity provider's response could not be verified.",
  no_email: "The identity provider did not share an email address.",
  unverified_email: "The identity provider has not verified that email address.",
  domain: "That email domain is not allowed to sign in here.",
  privileged: "Administrator accounts sign in with their password.",
  ambiguous_email: "More than one account uses that email address. Ask an administrator to link your identity.",
  unknown_user: "No account is linked to that identity. Ask an administrator to link it.",
  inactive: "That account is deactivated.",
  role: "The server's default single sign-on role is misconfigured.",
};

export default function Login({ onDone }) {
  const nav = useNavigate();
  const [health, setHealth] = useState(null);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [otp, setOtp] = useState("");
  const [mfaStep, setMfaStep] = useState(false);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const sso = oidcConfig();

  // The demo hint is only shown while the seeded demo accounts still exist.
  useEffect(() => {
    axios.get("/api/health/").then((r) => setHealth(r.data)).catch(() => setHealth(null));
  }, []);

  // Back from the identity provider: the callback left a one-time ticket (or
  // a reason) in the query string.
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const ticket = params.get("sso");
    const code = params.get("sso_error");
    if (code) {
      setErr(SSO_ERRORS[code] || "The identity provider declined the sign-in.");
      window.history.replaceState(null, "", "/login");
      return;
    }
    if (!ticket) return;
    const next = params.get("next") || "/";
    window.history.replaceState(null, "", "/login");
    setBusy(true);
    redeemSso(ticket)
      .then(() => { onDone?.(null); nav(next.startsWith("/") && !next.startsWith("//") ? next : "/"); })
      .catch((ex) => setErr(ex?.response?.data?.detail || SSO_ERRORS.state))
      .finally(() => setBusy(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Enter in any field submits, independent of implicit-submission quirks.
  function onEnter(e) {
    if (e.key === "Enter") {
      e.preventDefault();
      e.currentTarget.form?.requestSubmit();
    }
  }

  async function submit(e) {
    e.preventDefault();
    setErr("");
    setBusy(true);
    try {
      await login(username.trim(), password, mfaStep ? otp : undefined);
      onDone?.(null);
      nav("/");
    } catch (ex) {
      const data = ex?.response?.data;
      if (data?.mfa_required) {
        setMfaStep(true);
        setErr("");
      } else if (ex?.response?.status === 429) {
        setErr("Too many attempts. Wait a minute and try again.");
      } else if (mfaStep) {
        setErr("That authentication code isn't valid. Try again, or use a backup code.");
      } else {
        setErr("Incorrect username or password.");
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-bg px-4">
      <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.3, ease: [0.23, 1, 0.32, 1] }} className="w-full max-w-[400px]">
        <Panel as="div" className="p-6">
          <form onSubmit={submit} noValidate>
            <div className="flex items-center gap-3">
              <div className="flex h-9 w-9 items-center justify-center rounded-[10px] bg-accent font-semibold text-accent-ink" aria-hidden="true">C</div>
              <div>
                <p className="text-[15px] font-semibold tracking-[-0.01em] text-ink">Conformiti</p>
                <Label>SOC 2 · ISO 27001 · PCI</Label>
              </div>
            </div>
            <h1 className="mt-6 text-[20px] font-semibold tracking-[-0.02em] text-ink">{mfaStep ? "Two-factor authentication" : "Sign in"}</h1>
            <p className="mt-1 text-[13px] leading-snug text-muted">
              {mfaStep ? "Enter the 6-digit code from your authenticator app, or a backup code." : "Continuous compliance for SOC 2, ISO 27001 and PCI DSS."}
            </p>
            {err ? <div className="notice notice-err mt-4" role="alert">{err}</div> : null}
            {!mfaStep ? (
              <>
                <div className="mt-5">
                  <label htmlFor="login-username" className="field-label">Username</label>
                  <input id="login-username" name="username" autoComplete="username" className="input" value={username} onChange={(e) => setUsername(e.target.value)} onKeyDown={onEnter} autoFocus />
                </div>
                <div className="mt-4">
                  <label htmlFor="login-password" className="field-label">Password</label>
                  <input id="login-password" name="password" type="password" autoComplete="current-password" className="input" value={password} onChange={(e) => setPassword(e.target.value)} onKeyDown={onEnter} />
                </div>
              </>
            ) : (
              <div className="mt-5">
                <label htmlFor="login-otp" className="field-label">Authentication code</label>
                <input
                  id="login-otp"
                  name="otp"
                  className="input font-mono"
                  value={otp}
                  onChange={(e) => setOtp(e.target.value)}
                  onKeyDown={onEnter}
                  autoFocus
                  inputMode="text"
                  autoComplete="one-time-code"
                  placeholder="123456 or backup code"
                />
              </div>
            )}
            <Button type="submit" variant="primary" className="mt-5 w-full" disabled={busy || !username || !password}>
              {busy ? "Signing in…" : mfaStep ? "Verify" : "Sign in"}
            </Button>
            {sso.enabled && !mfaStep ? (
              <>
                <div className="my-4 flex items-center gap-3" aria-hidden="true">
                  <span className="h-px flex-1 bg-line" />
                  <Label>or</Label>
                  <span className="h-px flex-1 bg-line" />
                </div>
                <Button type="button" variant="secondary" className="w-full" disabled={busy}
                        onClick={() => window.location.assign("/api/auth/oidc/start/")}>
                  {sso.label}
                </Button>
              </>
            ) : null}
            {mfaStep ? (
              <button type="button" className="link mt-4" onClick={() => { setMfaStep(false); setOtp(""); setErr(""); }}>
                ← Back to password
              </button>
            ) : health?.demo_accounts ? (
              <p className="mt-4 text-center text-xs text-muted">
                Demo accounts: <span className="font-mono text-ink">admin</span> / <span className="font-mono text-ink">DemoPass123!</span>
                <span className="block text-2xs text-faint">also mia · owen · aria · val</span>
              </p>
            ) : null}
          </form>
        </Panel>
        <p className="mt-4 text-center font-mono text-2xs uppercase tracking-label text-faint">{health?.version ? `Conformiti v${health.version}` : ""}</p>
      </motion.div>
    </div>
  );
}
