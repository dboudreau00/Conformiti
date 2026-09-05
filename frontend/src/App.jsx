import { useCallback, useEffect, useState } from "react";
import { Navigate, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { AnimatePresence } from "framer-motion";
import api, { cookieMode, isAuthed, loadAuthConfig, logout, session } from "./api/client.js";
import ErrorBoundary from "./components/ErrorBoundary.jsx";
import { MobileNav, Sidebar } from "./components/layout/Sidebar.jsx";
import { TopBar } from "./components/layout/TopBar.jsx";
import { ShellContext } from "./shell.js";
import Login from "./pages/Login.jsx";
import Dashboard from "./pages/Dashboard.jsx";
import Controls from "./pages/Controls.jsx";
import Documents from "./pages/Documents.jsx";
import Analytics from "./pages/Analytics.jsx";
import Account from "./pages/Account.jsx";
import UserAudit from "./pages/UserAudit.jsx";
import Packages from "./pages/Packages.jsx";
import AuditLog from "./pages/AuditLog.jsx";
import Meetings from "./pages/Meetings.jsx";
import Groups from "./pages/Groups.jsx";
import Jira from "./pages/Jira.jsx";
import Risks from "./pages/Risks.jsx";
import Users from "./pages/Users.jsx";
import Vendors from "./pages/Vendors.jsx";
import Responsibilities from "./pages/Responsibilities.jsx";
import Questionnaire from "./pages/Questionnaire.jsx";

function Protected({ me, setMe }) {
  const nav = useNavigate();
  const location = useLocation();
  const [health, setHealth] = useState(null);
  const [counts, setCounts] = useState({});
  // null while the answer is unknown. In header mode localStorage answers
  // synchronously; in cookie mode the credential is invisible to script, so
  // the server is the only authority and the answer is a round trip. Rendering
  // the shell during that window would fire every page's queries as an
  // anonymous user and fill the console with 401s.
  const [signedIn, setSignedIn] = useState(() => (cookieMode() ? null : isAuthed()));

  useEffect(() => {
    let alive = true;
    (async () => {
      if (cookieMode() && signedIn === null) {
        const state = await session().catch(() => ({ authenticated: false }));
        if (!alive) return;
        setSignedIn(!!state.authenticated);
        if (!state.authenticated) return;
      } else if (!cookieMode() && !isAuthed()) {
        setSignedIn(false);
        return;
      } else if (signedIn === false) {
        // Already answered no. Falling through would fetch /users/me/ as an
        // anonymous user on the way to the login screen.
        return;
      }
      if (!me) {
        const r = await api.get("/users/me/").catch(() => null);
        if (alive && r) setMe(r.data);
      }
    })();
    return () => { alive = false; };
  }, [me, signedIn]);

  // Everything below waits for `me`. Firing before the session is confirmed
  // would put three 401s on the console for anyone opening a protected route
  // signed out -- and in cookie mode the confirmation is a round trip, so
  // there is a real window in which to do it.
  useEffect(() => {
    if (!me) return;
    api.get("/health/").then((r) => setHealth(r.data)).catch(() => {});
  }, [me]);

  // Sidebar badges: controls in progress, live risks, open access reviews.
  const refreshCounts = useCallback(() => {
    if (!me) return;
    api.get("/analytics/summary/").then((r) => {
      const s = r.data;
      setCounts((c) => ({ ...c, controls: s.controls?.by_status?.in_progress || 0, risks: s.risks?.open || 0 }));
    }).catch(() => {});
    if (me?.capabilities?.manage_users || me?.capabilities?.auditor) {
      api.get("/access-reviews/?status=open").then((r) => {
        const n = r.data.count ?? (r.data.results || r.data).length;
        setCounts((c) => ({ ...c, reviews: n }));
      }).catch(() => {});
    }
  }, [me]);

  useEffect(() => { refreshCounts(); }, [refreshCounts, location.pathname]);

  async function signOut() {
    await logout();
    // Order matters: clearing `me` re-runs the session effect, so the shell
    // has to already know the answer is no or it will fetch on the way out.
    setSignedIn(false);
    setMe(null);
    nav("/login");
  }

  if (signedIn === null) return null;   // still asking
  if (!signedIn) return <Navigate to="/login" replace />;

  return (
    <ShellContext.Provider value={{ me, health, counts, refreshCounts }}>
      <div className="flex min-h-screen w-full bg-bg">
        <Sidebar onSignOut={signOut} />
        <div className="flex min-w-0 flex-1 flex-col">
          <TopBar />
          <MobileNav onSignOut={signOut} />
          <div className="min-w-0 flex-1">
            <ErrorBoundary>
              <AnimatePresence mode="wait" initial={false}>
                <Routes location={location} key={location.pathname}>
                  <Route path="/" element={<Dashboard me={me} />} />
                  <Route path="/analytics" element={<Analytics me={me} />} />
                  <Route path="/controls" element={<Controls me={me} />} />
                  <Route path="/documents" element={<Documents me={me} />} />
                  <Route path="/users" element={<Users me={me} />} />
                  <Route path="/user-audit" element={<UserAudit me={me} />} />
                  <Route path="/packages" element={<Packages me={me} />} />
                  <Route path="/audit-log" element={<AuditLog me={me} />} />
                  <Route path="/meetings" element={<Meetings me={me} />} />
                  <Route path="/groups" element={<Groups me={me} />} />
                  <Route path="/risks" element={<Risks me={me} />} />
                  <Route path="/jira" element={<Jira me={me} />} />
                  <Route path="/vendors" element={<Vendors me={me} />} />
                  <Route path="/responsibilities" element={<Responsibilities me={me} />} />
                  <Route path="/settings" element={<Account me={me} onUpdate={setMe} />} />
                  {/* Routes from earlier releases */}
                  <Route path="/account" element={<Navigate to="/settings" replace />} />
                  <Route path="/audit" element={<Navigate to="/audit-log" replace />} />
                  <Route path="*" element={<Navigate to="/" replace />} />
                </Routes>
              </AnimatePresence>
            </ErrorBoundary>
          </div>
        </div>
      </div>
    </ShellContext.Provider>
  );
}

export default function App() {
  const [me, setMe] = useState(null);
  const [booted, setBooted] = useState(false);

  // Which transport is live decides how every later request is made, so it has
  // to be known before the first one goes out.
  useEffect(() => {
    loadAuthConfig().finally(() => setBooted(true));
  }, []);

  if (!booted) return null;
  return (
    <Routes>
      <Route path="/login" element={<Login onDone={setMe} />} />
      {/* The vendor's questionnaire: reached from an emailed link, no account. */}
      <Route path="/questionnaire/:token" element={<Questionnaire />} />
      <Route path="/*" element={<Protected me={me} setMe={setMe} />} />
    </Routes>
  );
}
