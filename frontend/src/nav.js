// Navigation model shared by the sidebar, the top bar and the validator.
// `badge` names a live counter supplied by the shell (see App.jsx).
export const NAV_SECTIONS = [
  {
    id: "workspace",
    label: "Workspace",
    items: [
      { id: "dashboard", label: "Dashboard", path: "/", icon: "LayoutDashboard" },
      { id: "analytics", label: "Analytics", path: "/analytics", icon: "ChartPie" },
      { id: "controls", label: "Controls", path: "/controls", icon: "ShieldCheck", badge: "controls" },
      { id: "documents", label: "Documents", path: "/documents", icon: "FileText" },
    ],
  },
  {
    id: "governance",
    label: "Governance",
    items: [
      { id: "users", label: "Users", path: "/users", icon: "Users" },
      { id: "user-audit", label: "User audit", path: "/user-audit", icon: "UserCheck", badge: "reviews" },
      { id: "packages", label: "Audit packages", path: "/packages", icon: "PackageCheck" },
      { id: "audit-log", label: "Audit log", path: "/audit-log", icon: "ScrollText" },
      { id: "meetings", label: "Meetings", path: "/meetings", icon: "CalendarClock" },
      { id: "groups", label: "Groups", path: "/groups", icon: "Flag" },
      { id: "risks", label: "Risks", path: "/risks", icon: "TriangleAlert", badge: "risks" },
      { id: "jira", label: "Jira", path: "/jira", icon: "Diamond" },
    ],
  },
  {
    id: "account",
    label: "Account",
    items: [{ id: "settings", label: "Settings", path: "/settings", icon: "Settings" }],
  },
];

export const NAV_LOOKUP = {
  "/": { title: "Dashboard", caption: "Compliance posture across SOC 2, ISO 27001 and PCI DSS" },
  "/analytics": { title: "Analytics", caption: "Readiness, coverage and ownership breakdowns" },
  "/controls": { title: "Controls", caption: "Control libraries mapped across three frameworks" },
  "/documents": { title: "Documents", caption: "Policies, procedures and evidence in your folders" },
  "/users": { title: "Users", caption: "Workspace membership, roles and folder grants" },
  "/user-audit": { title: "User audit", caption: "Periodic access review and attestation" },
  "/packages": { title: "Audit packages", caption: "Evidence sealed and issued to an external auditor" },
  "/audit-log": { title: "Audit log", caption: "Immutable record of every change and sign-in" },
  "/meetings": { title: "Meetings", caption: "Governance forum cadence and minutes" },
  "/groups": { title: "Champion groups", caption: "Inter-departmental compliance ownership" },
  "/risks": { title: "Risk register", caption: "Open, mitigating and accepted risk treatment" },
  "/jira": { title: "Jira boards", caption: "Remediation work linked to controls" },
  "/settings": { title: "Account", caption: "Profile, appearance and access" },
};
