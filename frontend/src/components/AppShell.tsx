import type { ReactNode } from "react";
import {
  ArrowUpDown,
  BarChart3,
  CircleDollarSign,
  FileCheck2,
  LayoutDashboard,
  Upload,
} from "lucide-react";
import { NavLink } from "react-router-dom";

const navigation = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard, end: true },
  { to: "/upload", label: "Upload & Mapping", icon: Upload, end: false },
  { to: "/review", label: "Transaction Review", icon: FileCheck2, end: false },
  { to: "/pnl", label: "Internal P&L", icon: BarChart3, end: false },
  { to: "/qbo", label: "QBO Sync", icon: ArrowUpDown, end: false },
  { to: "/reconciliation", label: "Reconciliation", icon: CircleDollarSign, end: false },
] as const;

export function AppShell({ children }: { children: ReactNode }) {
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand" aria-label="Finz Ledger Bridge">
          <span className="brand-mark" aria-hidden="true">F</span>
          <span>
            <strong>Finz</strong>
            <small>Ledger Bridge</small>
          </span>
        </div>
        <nav aria-label="Primary" className="primary-nav">
          {navigation.map(({ to, label, icon: Icon, end }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              className={({ isActive }) => (isActive ? "nav-link active" : "nav-link")}
            >
              <Icon aria-hidden="true" />
              <span>{label}</span>
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-foot">
          <span className="status-dot" aria-hidden="true" />
          Local review workspace
        </div>
      </aside>
      <main className="main-content">{children}</main>
    </div>
  );
}
