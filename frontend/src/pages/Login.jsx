import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import axios from "axios";
import { login, oidcConfig, redeemSso, samlConfig } from "../api/client.js";
import { getAssertion, passkeyErrorText, passkeysSupported } from "../api/webauthn.js";
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
  mfa_required: "This server requires a second factor for single sign-on. Sign in with your password once and enrol an authenticator, or have your identity provider assert one.",
};

const NO_FACTORS = { totp: false, passkey: false, passkey_suspect: 0 };

export default function Login({ onDone }) {
  const nav = useNavigate();
  const [health, setHealth] = useState(null);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [otp, setOtp] = useState("");
  const [mfaStep, setMfaStep] = useState(false);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  // What the server said after the password: which factors may satisfy the
  // second step, and the passkey challenge when one is on offer.
  const [factors, setFactors] = useState(NO_FACTORS);
  const [passkey, setPasskey] = useState(null);
  const [method, setMethod] = useState("code");
  // A single sign-on that still needs the local second factor: the ticket
  // waits here, never in the URL, while the person types the code.
  const [ssoTicket, setSsoTicket] = useState(null);
  const [ssoNext, setSsoNext] = useState("/");
  const sso = oidcConfig();
  const samlSso = samlConfig();
  const canPasskey = passkeysSupported();

  // The demo hint is only shown while the seeded demo accounts still exist.
  useEffect(() => {
    axios.get("/api/health/").then((r) => setHealth(r.data)).catch(() => setHealth(null));
  }, []);

  function challenge(data) {
    const f = { ...NO_FACTORS, ...(data?.factors || {}) };
    setFactors(f);
    setPasskey(data?.passkey || null);
    setMethod(f.passkey && canPasskey ? "passkey" : "code");
    setMfaStep(true);
    setErr("");
  }

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
    const safeNext = next.startsWith("/") && !next.startsWith("//") ? next : "/";
    window.history.replaceState(null, "", "/login");
    setBusy(true);
    redeemSso(ticket)
      .then((data) => {
        if (data?.mfa_required) {
          setSsoTicket(ticket);
          setSsoNext(safeNext);
          challenge(data);
          return;
        }
        onDone?.(null);
        nav(safeNext);
      })
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

  /** Complete the sign-in with a second factor, by either route. */
  async function finish(second) {
    if (ssoTicket) {
      const data = await redeemSso(ssoTicket, second);
      if (data?.mfa_required) throw Object.assign(new Error("mfa"), { response: { data: { code: "mfa_invalid" } } });
      onDone?.(null);
      nav(ssoNext);
      return;
    }
    await login(username.trim(), password, second);
    onDone?.(null);
    nav("/");
  }

  /** A passkey challenge answers once; after a refusal, ask for a fresh one. */
  async function refreshChallenge() {
    try {
      if (ssoTicket) {
        const data = await redeemSso(ssoTicket);
        if (data?.mfa_required) setPasskey(data.passkey || null);
      } else {
        await login(username.trim(), password);
      }
    } catch (ex) {
      if (ex?.response?.data?.mfa_required) setPasskey(ex.response.data.passkey || null);
    }
  }

  async function usePasskey() {
    if (!passkey) return;
    setErr("");
    setBusy(true);
    try {
      const credential = await getAssertion(passkey.options);
      await finish({ passkey: { state: passkey.state, credential } });
    } catch (ex) {
      const data = ex?.response?.data;
      if (ex?.response?.status === 429) {
        setErr("Too many attempts. Wait a minute and try again.");
      } else if (ssoTicket && data?.code && data.code !== "mfa_invalid") {
        resetToStart(SSO_ERRORS[data.code] || data.detail || SSO_ERRORS.state);
      } else {
        setErr(data?.detail || passkeyErrorText(ex));
        await refreshChallenge();
      }
    } finally {
      setBusy(false);
    }
  }

  function resetToStart(message) {
    setSsoTicket(null);
    setMfaStep(false);
    setOtp("");
    setFactors(NO_FACTORS);
    setPasskey(null);
    setErr(message || "");
  }

  async function submit(e) {
    e.preventDefault();
    setErr("");
    setBusy(true);
    try {
      if (mfaStep) {
        await finish({ otp });
        return;
      }
      await login(username.trim(), password);
      onDone?.(null);
      nav("/");
    } catch (ex) {
      const data = ex?.response?.data;
      if (data?.mfa_required) {
        challenge(data);
      } else if (ex?.response?.status === 429) {
        setErr("Too many attempts. Wait a minute and try again.");
      } else if (ssoTicket && data?.code && data.code !== "mfa_invalid") {
        // The ticket is gone (expired, or too many tries): back to the start.
        resetToStart(SSO_ERRORS[data.code] || data.detail || SSO_ERRORS.state);
      } else if (mfaStep) {
        setErr(data?.detail && !/invalid authentication code/i.test(String(data.detail))
          ? String(data.detail)
          : "That authentication code isn't valid. Try again, or use a backup code.");
      } else {
        setErr("Incorrect username or password.");
      }
    } finally {
      setBusy(false);
    }
  }

  // Nothing usable: every passkey is suspect and there is no authenticator app.
  const lockedOut = mfaStep && !factors.totp && !factors.passkey && factors.passkey_suspect > 0;
  const showCode = mfaStep && !lockedOut && (method === "code" || !factors.passkey);
  const showPasskey = mfaStep && !lockedOut && factors.passkey && method === "passkey";

  const heading = mfaStep ? "Two-factor authentication" : "Sign in";
  let intro = "Continuous compliance for SOC 2, ISO 27001 and PCI DSS.";
  if (lockedOut) {
    intro = "Your only passkey was disabled because it may have been cloned, and there is no "
      + "authenticator app on this account. Ask an administrator to reset your second factor.";
  } else if (showPasskey) {
    intro = ssoTicket
      ? "Your identity provider signed you in, but did not assert a second factor. Confirm with your passkey."
      : "Confirm it's you with your passkey or security key.";
  } else if (mfaStep) {
    intro = ssoTicket
      ? "Your identity provider signed you in, but did not assert a second factor. Enter the code from your authenticator app, or a backup code."
      : "Enter the 6-digit code from your authenticator app, or a backup code.";
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
            <h1 className="mt-6 text-[20px] font-semibold tracking-[-0.02em] text-ink">{heading}</h1>
            <p className="mt-1 text-[13px] leading-snug text-muted">{intro}</p>
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
            ) : null}
            {showCode ? (
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
            ) : null}
            {showPasskey ? (
              <Button type="button" variant="primary" className="mt-5 w-full" disabled={busy || !passkey} onClick={usePasskey} autoFocus>
                {busy ? "Waiting for your passkey…" : "Use passkey"}
              </Button>
            ) : !lockedOut ? (
              <Button type="submit" variant="primary" className="mt-5 w-full"
                      disabled={busy || (mfaStep ? !otp : (!username || !password))}>
                {busy ? "Signing in…" : mfaStep ? "Verify" : "Sign in"}
              </Button>
            ) : null}
            {mfaStep && !lockedOut && factors.passkey && factors.totp ? (
              <button type="button" className="link mt-3 block" disabled={busy}
                      onClick={() => { setErr(""); setMethod(method === "passkey" ? "code" : "passkey"); }}>
                {method === "passkey" ? "Use a code instead" : "Use a passkey instead"}
              </button>
            ) : null}
            {mfaStep && !lockedOut && factors.passkey && !canPasskey && !factors.totp ? (
              <p className="mt-3 text-xs text-muted">This browser cannot use passkeys. Sign in from a browser that can, or ask an administrator to reset your second factor.</p>
            ) : null}
            {(sso.enabled || samlSso.enabled) && !mfaStep ? (
              <>
                <div className="my-4 flex items-center gap-3" aria-hidden="true">
                  <span className="h-px flex-1 bg-line" />
                  <Label>or</Label>
                  <span className="h-px flex-1 bg-line" />
                </div>
                {sso.enabled ? (
                  <Button type="button" variant="secondary" className="w-full" disabled={busy}
                          onClick={() => window.location.assign("/api/auth/oidc/start/")}>
                    {sso.label}
                  </Button>
                ) : null}
                {samlSso.enabled ? (
                  <Button type="button" variant="secondary" className={sso.enabled ? "mt-2 w-full" : "w-full"} disabled={busy}
                          onClick={() => window.location.assign("/api/auth/saml/start/")}>
                    {samlSso.label}
                  </Button>
                ) : null}
              </>
            ) : null}
            {mfaStep ? (
              <button type="button" className="link mt-4" onClick={() => resetToStart("")}>
                {ssoTicket ? "← Start over" : "← Back to password"}
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
