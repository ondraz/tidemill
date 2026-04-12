import { NavLink } from 'react-router-dom'
import {
  LayoutDashboard,
  TrendingUp,
  UserMinus,
  Users,
  DollarSign,
  FlaskConical,
  BarChart3,
  Settings,
} from 'lucide-react'

const navItems = [
  { to: '/', icon: BarChart3, label: 'Overview' },
  { to: '/dashboards', icon: LayoutDashboard, label: 'Dashboards' },
]

const reportItems = [
  { to: '/reports/mrr', icon: TrendingUp, label: 'MRR' },
  { to: '/reports/churn', icon: UserMinus, label: 'Churn' },
  { to: '/reports/retention', icon: Users, label: 'Retention' },
  { to: '/reports/ltv', icon: DollarSign, label: 'LTV' },
  { to: '/reports/trials', icon: FlaskConical, label: 'Trials' },
]

function NavItem({ to, icon: Icon, label }: { to: string; icon: React.ElementType; label: string }) {
  return (
    <NavLink
      to={to}
      end={to === '/'}
      className={({ isActive }) =>
        `flex items-center gap-2.5 px-3 py-1.5 rounded-md text-sm ${
          isActive
            ? 'bg-primary/10 text-primary font-medium'
            : 'text-muted-foreground hover:bg-accent hover:text-foreground'
        }`
      }
    >
      <Icon className="w-4 h-4 shrink-0" />
      {label}
    </NavLink>
  )
}

export function Sidebar() {
  return (
    <aside className="w-56 shrink-0 border-r border-border bg-card h-screen sticky top-0 flex flex-col">
      <div className="px-4 py-4 border-b border-border">
        <h1 className="text-lg font-semibold tracking-tight">Tidemill</h1>
      </div>
      <nav className="flex-1 px-2 py-3 space-y-0.5 overflow-y-auto">
        {navItems.map((item) => (
          <NavItem key={item.to} {...item} />
        ))}

        <div className="pt-4 pb-1 px-3 text-xs font-medium text-muted-foreground uppercase tracking-wider">
          Reports
        </div>
        {reportItems.map((item) => (
          <NavItem key={item.to} {...item} />
        ))}

        <div className="pt-4 pb-1 px-3 text-xs font-medium text-muted-foreground uppercase tracking-wider">
          Settings
        </div>
        <NavItem to="/settings/api-keys" icon={Settings} label="API Keys" />
      </nav>
    </aside>
  )
}
