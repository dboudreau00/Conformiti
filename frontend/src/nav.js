// Navigation model shared by the shell (top bar, side menu, mobile sheet) and
// the validator.
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
      { id: "vendors", label: "Vendors", path: "/vendors", icon: "Building2" },
      { id: "responsibilities", label: "Responsibility matrix", path: "/responsibilities", icon: "LayoutGrid" },
      { id: "audit-log", label: "Audit log", path: "/audit-log", icon: "ScrollText" },
      { id: "meetings", label: "Meetings", path: "/meetings", icon: "CalendarClock" },
      { id: "groups", label: "Champion groups", path: "/groups", icon: "Flag" },
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

// An external auditor is a guest of one engagement, not a member of the
// organisation. The API refuses them the risk register, the vendor file, the
// control library, the user directory, the calendar and the rest (see
// accounts/permissions.py), so the nav must not offer it either. These are
// the ids that remain: the packages issued to them, the evidence in the
// folders granted with them, the access reviews and the trail.
const AUDITOR_NAV = new Set(["documents", "packages", "user-audit", "audit-log", "settings"]);

export function navSections(me) {
  if (!me?.capabilities?.auditor) return NAV_SECTIONS;
  return NAV_SECTIONS
    .map((section) => ({ ...section, items: section.items.filter((i) => AUDITOR_NAV.has(i.id)) }))
    .filter((section) => section.items.length > 0);
}

export const NAV_LOOKUP = {
  "/": { title: "Dashboard", caption: "Compliance posture across every framework in this workspace" },
  "/analytics": { title: "Analytics", caption: "Readiness, coverage and ownership breakdowns" },
  "/controls": { title: "Controls", caption: "Every control library in this workspace, with its crosswalk" },
  "/documents": { title: "Documents", caption: "Policies, procedures and evidence in your folders" },
  "/users": { title: "Users", caption: "Workspace membership, roles and folder grants" },
  "/user-audit": { title: "User audit", caption: "Periodic access review and attestation" },
  "/packages": { title: "Audit packages", caption: "Evidence sealed and issued to an external auditor" },
  "/vendors": { title: "Vendors", caption: "Third-party risk, assurance on file and shared responsibility" },
  "/responsibilities": { title: "Responsibility matrix", caption: "Who is responsible, accountable, consulted and informed per control" },
  "/audit-log": { title: "Audit log", caption: "Read-only record of every change and sign-in" },
  "/meetings": { title: "Meetings", caption: "Governance forum cadence and minutes" },
  "/groups": { title: "Champion groups", caption: "Inter-departmental compliance ownership" },
  "/risks": { title: "Risk register", caption: "Open, mitigating and accepted risk treatment" },
  "/jira": { title: "Jira boards", caption: "Remediation work linked to controls" },
  "/settings": { title: "Settings", caption: "Profile, appearance, security, notifications and access" },
};

// Where the shell draws each section that navSections(me) returns:
//   workspace   the tabs in the top bar
//   governance  the Governance panel in the top bar
//   account     the user menu, except the items an add-on appends to it
//               (their ids carry the add-on's reserved prefix)
//   anything else, and those appended items, the left side menu
// It reads navSections at call time, never NAV_SECTIONS, and decides from the
// section ids alone, never from a flag on `me`, so an add-on that wraps
// navSections lands in the right place and a section the core does not define
// needs no change here. A side menu with no items is absent.
const isOverlayItem = (item) => String(item.id).startsWith("pro-");

export function shellNav(me) {
  const sections = navSections(me);
  const items = (id) => sections.find((s) => s.id === id)?.items ?? [];
  const account = items("account");
  const side = sections.filter((s) => !["workspace", "governance", "account", "pro-account"].includes(s.id));
  const foot = [...account.filter(isOverlayItem), ...items("pro-account")];
  return {
    tabs: items("workspace"),
    governance: items("governance"),
    account: account.filter((item) => !isOverlayItem(item)),
    side: side.filter((s) => s.items.length > 0),
    foot,
  };
}

/** The caption under a page's title, read at call time because an add-on
 *  merges its own entries (and may override one) after this file has run. */
export function navCaption(path) {
  return NAV_LOOKUP[path]?.caption ?? "";
}
