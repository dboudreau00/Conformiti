import { useCallback, useEffect, useState } from "react";
import { Navigate, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { AnimatePresence } from "framer-motion";
import api, { cookieMode, isAuthed, loadAuthConfig, logout, session } from "./api/client.js";
import ErrorBoundary, { ChromeFallback } from "./components/ErrorBoundary.jsx";
import { NotForAuditors } from "./components/layout/NotForAuditors.jsx";
import { SideMenu } from "./components/layout/SideMenu.jsx";
import { SkipLink } from "./components/layout/SkipLink.jsx";
import { TopBar } from "./components/layout/TopBar.jsx";
import { openToAuditor } from "./nav.js";
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
  // Whether /users/me/ has answered, or failed. Who is signed in decides what
  // a page may ask for, so no routed page is drawn before then.
  const [meKnown, setMeKnown] = useState(!!me);

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
        if (!alive) return;
        if (r) setMe(r.data);
        // A failed answer still lets the pages draw: each shows its own
        // refusal, as before, rather than nothing at all.
        setMeKnown(true);
      }
    })();
    return () => { alive = false; };
  }, [me, signedIn]);

  // Everything below waits for `me`. Firing before the session is confirmed
  // would put three 401s on the console for anyone opening a protected route
  // signed out, and in cookie mode the confirmation is a round trip, so
  // there is a real window in which to do it.
  useEffect(() => {
    if (!me) return;
    api.get("/health/").then((r) => setHealth(r.data)).catch(() => {});
  }, [me]);

  // Nav badges: controls in progress, live risks, open access reviews.
  const refreshCounts = useCallback(() => {
    if (!me) return;
    if (me?.capabilities?.auditor) return;  // the API refuses these requests for auditors
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

  // A page waits for the session before it is drawn and asks for anything.
  // An external auditor at an address the menu never offers them (typed, or
  // an old bookmark) then sees one plain notice: the API refuses the request
  // either way, and the page used to show that refusal twice under a Try
  // again that could not succeed.
  const page = (path, element) => {
    if (!me && !meKnown) return null;
    return me?.capabilities?.auditor && !openToAuditor(path) ? <NotForAuditors /> : element;
  };

  return (
    <ShellContext.Provider value={{ me, health, counts, refreshCounts }}>
      <div className="min-h-screen w-full bg-bg">
        <SkipLink />
        <ErrorBoundary fallback={<ChromeFallback />}>
          <TopBar onSignOut={signOut} />
        </ErrorBoundary>
        <div className="flex items-start">
          <ErrorBoundary fallback={null}>
            <SideMenu />
          </ErrorBoundary>
          <div className="min-w-0 flex-1">
            <ErrorBoundary>
              <AnimatePresence mode="wait" initial={false}>
                <Routes location={location} key={location.pathname}>
                  {/* The dashboard reads the whole programme (analytics,
                      frameworks), which an external auditor may not: send
                      them to the packages issued to them instead. */}
                  <Route path="/" element={me?.capabilities?.auditor
                    ? <Navigate to="/packages" replace />
                    : <Dashboard me={me} />} />
                  <Route path="/analytics" element={page("/analytics", <Analytics me={me} />)} />
                  <Route path="/controls" element={page("/controls", <Controls me={me} />)} />
                  <Route path="/documents" element={page("/documents", <Documents me={me} />)} />
                  <Route path="/users" element={page("/users", <Users me={me} />)} />
                  <Route path="/user-audit" element={page("/user-audit", <UserAudit me={me} />)} />
                  <Route path="/packages" element={page("/packages", <Packages me={me} />)} />
                  <Route path="/audit-log" element={page("/audit-log", <AuditLog me={me} />)} />
                  <Route path="/meetings" element={page("/meetings", <Meetings me={me} />)} />
                  <Route path="/groups" element={page("/groups", <Groups me={me} />)} />
                  <Route path="/risks" element={page("/risks", <Risks me={me} />)} />
                  <Route path="/jira" element={page("/jira", <Jira me={me} />)} />
                  <Route path="/vendors" element={page("/vendors", <Vendors me={me} />)} />
                  <Route path="/responsibilities" element={page("/responsibilities", <Responsibilities me={me} />)} />
                  <Route path="/settings" element={page("/settings", <Account me={me} onUpdate={setMe} />)} />
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
