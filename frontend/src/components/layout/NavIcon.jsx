import {
  Building2Icon,
  CalendarClockIcon,
  ChartPieIcon,
  DiamondIcon,
  FileTextIcon,
  FlagIcon,
  LayoutDashboardIcon,
  LayoutGridIcon,
  PackageCheckIcon,
  ScrollTextIcon,
  SettingsIcon,
  ShieldCheckIcon,
  TriangleAlertIcon,
  UserCheckIcon,
  UsersIcon,
} from "lucide-react";

const ICONS = {
  LayoutDashboard: LayoutDashboardIcon,
  ChartPie: ChartPieIcon,
  ShieldCheck: ShieldCheckIcon,
  FileText: FileTextIcon,
  Users: UsersIcon,
  UserCheck: UserCheckIcon,
  PackageCheck: PackageCheckIcon,
  ScrollText: ScrollTextIcon,
  CalendarClock: CalendarClockIcon,
  Flag: FlagIcon,
  TriangleAlert: TriangleAlertIcon,
  Diamond: DiamondIcon,
  Building2: Building2Icon,
  LayoutGrid: LayoutGridIcon,
  Settings: SettingsIcon,
};

export function NavIcon({ name, className }) {
  const Cmp = ICONS[name] ?? LayoutDashboardIcon;
  return <Cmp className={className} strokeWidth={1.75} aria-hidden="true" />;
}
