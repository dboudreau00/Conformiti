import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import axios from "axios";
import { login, oidcConfig, redeemSso, samlConfig } from "../api/client.js";
import { getAssertion, passkeyErrorText, passkeysSupported } from "../api/webauthn.js";
import { ConformitiLogo } from "../components/brand/ConformitiLogo.jsx";
import { Button } from "../components/ui/Button.jsx";
import { Panel } from "../components/ui/Panel.jsx";

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

const NO_FACTORS = { totp: false, passkey: false, passkey_suspect: 0, backup_codes: false };

// Why a sign-in request failed, when the answer was not about the credentials
// at all; null when it was (a JSON 400, or a 401) or is the throttle (429),
// so the caller's own wording applies. A CSRF or origin refusal is the
// server's configuration and an error page or silence is the server itself:
// telling someone with the right password that it is wrong sends them after
// the wrong problem.
function serverRefusal(ex) {
  const res = ex?.response;
  if (!res) {
    return ex?.isAxiosError
      ? "The server could not be reached. Check your connection and try again in a moment."
      : "Sign-in could not be completed in this browser. Reload the page and try again.";
  }
  const { status, data } = res;
  const detail = typeof data?.detail === "string" ? data.detail : "";
  if (status >= 500) {
    // 502 to 504 is a proxy (nginx, or the Vite dev server) with no backend
    // answering behind it; a 500 is the backend failing.
    return `The server could not complete the sign-in (HTTP ${status}). Try again in a moment. `
      + "If it keeps happening, tell your administrator"
      + (status >= 502 && status <= 504 ? ": the backend may be down." : ".");
  }
  if (status === 403) {
    // Django's CSRF check. "Origin checking failed - X does not match any
    // trusted origins", or the Referer form of the same sentence (an https
    // request that carried no Origin): this address is not among
    // CSRF_TRUSTED_ORIGINS, which is the fix.
    if (/origin checking failed|does not match any trusted origins/i.test(detail)) {
      return `This server does not trust the address you opened it from (${window.location.origin}), `
        + "so it refused the sign-in. An administrator decides which addresses it accepts: "
        + "its allowed origins, set in CSRF_TRUSTED_ORIGINS.";
    }
    // The other Referer reasons ("no Referer", "Referer is malformed", "is
    // insecure while host is secure") are the browser's doing, over https
    // with no Origin header: a privacy setting or extension withheld the
    // referrer. The allowed origins would not change the answer.
    if (/referer checking failed/i.test(detail)) {
      return `The server refused the sign-in (${detail.replace(/\.$/, "")}). `
        + "Your browser did not send a usable referrer with it, which the server requires over https. "
        + "A privacy setting or extension that strips referrers usually does this: allow them for this site "
        + "and try again.";
    }
    // The rest of the CSRF check (no cookie or token to echo: cookies
    // blocked, or secure cookies over plain http), or a proxy's own refusal.
    return `The server refused the sign-in (${detail.replace(/\.$/, "") || "HTTP 403"}). `
      + "Reload the page and try again. If it keeps happening, tell your administrator"
      + (/csrf/i.test(detail) ? ": the server's security settings may not match this address." : ".");
  }
  if (status === 400 && (data === null || typeof data !== "object")) {
    // Not DRF's JSON: Django's own "Bad Request (400)" page, which is what a
    // host name missing from DJANGO_ALLOWED_HOSTS gets on every request.
    return "The server refused the request before checking your password (HTTP 400). "
      + "The address you opened it from is probably not one of its allowed host names "
      + "(DJANGO_ALLOWED_HOSTS), which an administrator sets.";
  }
  // No status at all is the refusal finish() builds for a wrong step-up code.
  if (!status || status === 400 || status === 401 || status === 429) return null;
  return `Sign-in failed (HTTP ${status}). Try again in a moment. If it keeps happening, tell your administrator.`;
}

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

  // The demo hint is only shown while the seeded demo accounts still exist,
  // and the first-administrator hint only while no account exists at all.
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
      const refused = serverRefusal(ex);
      if (data?.mfa_required) {
        challenge(data);
      } else if (ex?.response?.status === 429) {
        setErr("Too many attempts. Wait a minute and try again.");
      } else if (refused) {
        setErr(refused);
      } else if (ssoTicket && data?.code && data.code !== "mfa_invalid") {
        // The ticket is gone (expired, or too many tries): back to the start.
        resetToStart(SSO_ERRORS[data.code] || data.detail || SSO_ERRORS.state);
      } else if (mfaStep) {
        setErr(data?.detail && !/invalid authentication code/i.test(String(data.detail))
          ? String(data.detail)
          : "That authentication code isn't valid. Try again, or use a backup code.");
      } else if (ex?.response?.status === 401 && /workspace is archived/i.test(String(data?.detail || ""))) {
        // The password was right; the organisation it belongs to is closed.
        setErr(String(data.detail));
      } else {
        setErr("Incorrect username or password.");
      }
    } finally {
      setBusy(false);
    }
  }

  // Something typed can satisfy the step: an authenticator code, or a backup
  // code -- which a passkey-only account holds too.
  const codeWorks = factors.totp || factors.backup_codes;
  // Nothing usable: every passkey is suspect, no app, no codes left.
  const lockedOut = mfaStep && !codeWorks && !factors.passkey && factors.passkey_suspect > 0;
  const showCode = mfaStep && !lockedOut && (method === "code" || !factors.passkey);
  const showPasskey = mfaStep && !lockedOut && factors.passkey && method === "passkey";

  const heading = mfaStep ? "Two-factor authentication" : "Sign in";
  let intro = "Continuous compliance, on your own hardware.";
  if (lockedOut) {
    intro = "Your only passkey was disabled because it may have been cloned, and there is no "
      + "authenticator app or backup code left on this account. Ask an administrator to reset your second factor.";
  } else if (mfaStep && showCode && !factors.totp) {
    intro = ssoTicket
      ? "Your identity provider signed you in, but did not assert a second factor. Enter one of your backup codes."
      : "Enter one of your backup codes.";
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
            <ConformitiLogo size={40} />
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
            {mfaStep && !lockedOut && factors.passkey && codeWorks ? (
              <button type="button" className="link mt-3 block" disabled={busy}
                      onClick={() => { setErr(""); setMethod(method === "passkey" ? "code" : "passkey"); }}>
                {method === "passkey" ? (factors.totp ? "Use a code instead" : "Use a backup code instead") : "Use a passkey instead"}
              </button>
            ) : null}
            {mfaStep && !lockedOut && factors.passkey && !canPasskey && !codeWorks ? (
              <p className="mt-3 text-xs text-muted">This browser cannot use passkeys. Sign in from a browser that can, or ask an administrator to reset your second factor.</p>
            ) : null}
            {(sso.enabled || samlSso.enabled) && !mfaStep ? (
              <>
                <div className="my-4 flex items-center gap-3" aria-hidden="true">
                  <span className="h-px flex-1 bg-line" />
                  <span className="font-mono text-2xs uppercase tracking-label text-faint">or</span>
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
                This installation still has its seeded demo accounts.
                <span className="block text-2xs text-faint">
                  Their shared password was printed once when the demo data was seeded (in the
                  backend log with Docker), on the line that starts <span className="font-mono">Sign in as</span>. Retire them with
                  <span className="font-mono"> manage.py remove_demo_data</span> before real use.
                </span>
              </p>
            ) : health?.first_admin_needed === true ? (
              // Only while no active account exists at all, so a deployment
              // anyone signs in to never shows it.
              <p className="mt-4 text-center text-xs text-muted">
                This installation has no accounts yet.
                <span className="block text-2xs text-faint">
                  Create the first administrator on the server with
                  <span className="font-mono"> manage.py createsuperuser</span> (with Docker:
                  <span className="font-mono"> docker compose exec backend python manage.py createsuperuser</span>),
                  then sign in here.
                </span>
              </p>
            ) : null}
            {!mfaStep && health?.first_admin_needed !== true ? (
              <p className="mt-4 text-center text-xs text-muted">Forgotten your password? An administrator can set a new one for you from the Users page.</p>
            ) : null}
          </form>
        </Panel>
        <p className="mt-4 text-center font-mono text-2xs uppercase tracking-label text-faint">{health?.version ? `Conformiti v${health.version}` : ""}</p>
      </motion.div>
    </div>
  );
}
