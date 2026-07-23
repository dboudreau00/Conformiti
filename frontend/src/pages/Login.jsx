import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { login } from "../api/client.js";

export default function Login({ onDone }) {
  const nav = useNavigate();
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("");
  const [otp, setOtp] = useState("");
  const [mfaStep, setMfaStep] = useState(false);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e) {
    e.preventDefault();
    setErr(""); setBusy(true);
    try {
      await login(username, password, mfaStep ? otp : undefined);
      onDone?.(null);
      nav("/");
    } catch (ex) {
      const data = ex?.response?.data;
      if (data?.mfa_required) {
        setMfaStep(true);
        setErr("");
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
    <div className="login-wrap">
      <form className="login-card" onSubmit={submit}>
        <div className="brand">
          <div className="brand-mark">C</div>
          <div className="brand-name" style={{ color: "var(--ink)" }}>Conformiti</div>
        </div>
        <h2 className="login-title">{mfaStep ? "Two-factor authentication" : "Sign in"}</h2>
        <p className="login-sub">
          {mfaStep
            ? "Enter the 6-digit code from your authenticator app, or a backup code."
            : "Continuous compliance for SOC 2, ISO 27001 and PCI DSS."}
        </p>
        {err && <div className="error">{err}</div>}
        {!mfaStep ? (
          <>
            <div className="field">
              <label>Username</label>
              <input value={username} onChange={(e) => setUsername(e.target.value)} autoFocus />
            </div>
            <div className="field">
              <label>Password</label>
              <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} />
            </div>
          </>
        ) : (
          <div className="field">
            <label>Authentication code</label>
            <input value={otp} onChange={(e) => setOtp(e.target.value)} autoFocus
                   inputMode="text" autoComplete="one-time-code" placeholder="123456 or backup code" />
          </div>
        )}
        <button className="btn primary" style={{ width: "100%" }} disabled={busy}>
          {busy ? "Signing in…" : mfaStep ? "Verify" : "Sign in"}
        </button>
        {mfaStep ? (
          <div className="login-hint" style={{ cursor: "pointer" }}
               onClick={() => { setMfaStep(false); setOtp(""); setErr(""); }}>
            ← Back to password
          </div>
        ) : (
          <div className="login-hint">Demo: admin / DemoPass123!</div>
        )}
      </form>
    </div>
  );
}
