import { useEffect, useState } from "react";
import { Navigate, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import api, { isAuthed, logout } from "./api/client.js";
import NotificationBell from "./components/NotificationBell.jsx";
import ErrorBoundary from "./components/ErrorBoundary.jsx";
import { getTheme, setTheme } from "./theme.js";
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

const NAV = [
  { to: "/", label: "Dashboard", icon: "▣" },
  { to: "/analytics", label: "Analytics", icon: "◔" },
  { to: "/controls", label: "Controls", icon: "❑" },
  { to: "/documents", label: "Documents", icon: "🗎" },
];

const GOV_NAV = [
  { to: "/users", label: "Users", icon: "◉" },
  { to: "/user-audit", label: "User audit", icon: "▦" },
  { to: "/audit", label: "Audit log", icon: "≣" },
  { to: "/meetings", label: "Meetings", icon: "▤" },
  { to: "/groups", label: "Groups", icon: "⚑" },
  { to: "/risks", label: "Risks", icon: "△" },
  { to: "/jira", label: "Jira", icon: "◈" },
];

const TITLES = {
  "/": "Dashboard",
  "/analytics": "Analytics",
  "/controls": "Controls",
  "/documents": "Documents",
  "/users": "User management",
  "/user-audit": "User audit",
  "/audit": "Audit log",
  "/meetings": "Meeting minutes",
  "/groups": "Champion groups",
  "/risks": "Risk register",
  "/jira": "Jira boards",
  "/account": "Account",
};

function Shell({ me, children }) {
  const nav = useNavigate();
  const loc = useLocation();
  const title = TITLES[loc.pathname] || "Dashboard";
  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">C</div>
          <div>
            <div className="brand-name">Conformiti</div>
            <div className="brand-sub">SOC 2 · ISO 27001 · PCI</div>
          </div>
        </div>
        <div className="nav-label">Workspace</div>
        {NAV.map((n) => (
          <div
            key={n.to}
            className={"nav-item" + (loc.pathname === n.to ? " active" : "")}
            onClick={() => nav(n.to)}
          >
            <span className="ic">{n.icon}</span> {n.label}
          </div>
        ))}
        <div className="nav-label">Governance</div>
        {GOV_NAV.map((n) => (
          <div
            key={n.to}
            className={"nav-item" + (loc.pathname === n.to ? " active" : "")}
            onClick={() => nav(n.to)}
          >
            <span className="ic">{n.icon}</span> {n.label}
          </div>
        ))}
        <div className="nav-label">Account</div>
        <div
          className={"nav-item" + (loc.pathname === "/account" ? " active" : "")}
          onClick={() => nav("/account")}
        >
          <span className="ic">⚙</span> Settings
        </div>
        <div className="sidebar-foot">
          <div className="who" onClick={() => nav("/account")} title="Account settings">
            {me?.full_name || me?.username || "…"}
            <small>{me?.role_detail?.name || "No role"}</small>
          </div>
          <div className="signout" onClick={() => { logout(); nav("/login"); }}>
            Sign out
          </div>
        </div>
      </aside>
      <div className="main">
        <div className="topbar">
          <h1>{title}</h1>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <ThemeToggle />
            <NotificationBell />
          </div>
        </div>
        <div className="content">{children}</div>
      </div>
    </div>
  );
}

function Protected({ me, setMe }) {
  const nav = useNavigate();
  useEffect(() => {
    if (!isAuthed()) { nav("/login"); return; }
    if (!me) api.get("/users/me/").then((r) => setMe(r.data)).catch(() => {});
  }, [me]);
  if (!isAuthed()) return <Navigate to="/login" replace />;
  return (
    <Shell me={me}>
      <ErrorBoundary>
        <Routes>
        <Route path="/" element={<Dashboard me={me} />} />
        <Route path="/analytics" element={<Analytics me={me} />} />
        <Route path="/controls" element={<Controls me={me} />} />
        <Route path="/documents" element={<Documents me={me} />} />
        <Route path="/user-audit" element={<UserAudit me={me} />} />
        <Route path="/audit" element={<AuditLog me={me} />} />
        <Route path="/meetings" element={<Meetings me={me} />} />
        <Route path="/groups" element={<Groups me={me} />} />
        <Route path="/users" element={<Users me={me} />} />
        <Route path="/risks" element={<Risks me={me} />} />
        <Route path="/jira" element={<Jira me={me} />} />
        <Route path="/account" element={<Account me={me} onUpdate={setMe} />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
        </ErrorBoundary>
    </Shell>
  );
}

function ThemeToggle() {
  const [t, setT] = useState(getTheme());
  function flip() {
    const next = t.endsWith("-dark") ? t.slice(0, -5) : t + "-dark";
    setTheme(next);
    setT(next);
  }
  return (
    <button className="bell-btn" onClick={flip}
            title="Toggle light / dark — more themes in Account → Appearance"
            aria-label="Toggle dark mode">
      {t.endsWith("-dark") ? "☀" : "◐"}
    </button>
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
