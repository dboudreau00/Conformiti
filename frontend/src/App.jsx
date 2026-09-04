import { useCallback, useEffect, useState } from "react";
import { Navigate, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { AnimatePresence } from "framer-motion";
import api, { isAuthed, logout } from "./api/client.js";
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
import AuditLog from "./pages/AuditLog.jsx";
import Meetings from "./pages/Meetings.jsx";
import Groups from "./pages/Groups.jsx";
import Jira from "./pages/Jira.jsx";
import Risks from "./pages/Risks.jsx";
import Users from "./pages/Users.jsx";

function Protected({ me, setMe }) {
  const nav = useNavigate();
  const location = useLocation();
  const [health, setHealth] = useState(null);
  const [counts, setCounts] = useState({});

  useEffect(() => {
    if (!isAuthed()) { nav("/login"); return; }
    if (!me) api.get("/users/me/").then((r) => setMe(r.data)).catch(() => {});
  }, [me]);

  useEffect(() => {
    api.get("/health/").then((r) => setHealth(r.data)).catch(() => {});
  }, []);

  // Sidebar badges: controls in progress, live risks, open access reviews.
  const refreshCounts = useCallback(() => {
    if (!isAuthed()) return;
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
    setMe(null);
    nav("/login");
  }

  if (!isAuthed()) return <Navigate to="/login" replace />;

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
                  <Route path="/audit-log" element={<AuditLog me={me} />} />
                  <Route path="/meetings" element={<Meetings me={me} />} />
                  <Route path="/groups" element={<Groups me={me} />} />
                  <Route path="/risks" element={<Risks me={me} />} />
                  <Route path="/jira" element={<Jira me={me} />} />
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
  return (
    <Routes>
      <Route path="/login" element={<Login onDone={setMe} />} />
      <Route path="/*" element={<Protected me={me} setMe={setMe} />} />
    </Routes>
  );
}
