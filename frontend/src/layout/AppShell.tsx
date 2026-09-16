import { NavLink, Outlet } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { useTheme } from '../theme/ThemeContext'
import { Badge } from '../components/Badge'
import type { DomainRole } from '../api/types'

const ROLE_LABELS: Record<DomainRole, string> = {
  reader: 'Reader',
  contributor: 'Contributor',
  domain_admin: 'Admin',
}

function navLinkClass({ isActive }: { isActive: boolean }) {
  return isActive ? 'sidebar-link active' : 'sidebar-link'
}

function domainLinkClass({ isActive }: { isActive: boolean }) {
  return isActive ? 'sidebar-domain active' : 'sidebar-domain'
}

export function AppShell() {
  const { user, domains, logout } = useAuth()
  const { theme, setTheme } = useTheme()

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="sidebar-brand">RAG Console</div>

        <nav className="sidebar-nav">
          <NavLink to="/query" className={navLinkClass}>
            Query
          </NavLink>
          <NavLink to="/domains" end className={navLinkClass}>
            Domains
          </NavLink>
          {user?.is_platform_admin && (
            <NavLink to="/admin/users" className={navLinkClass}>
              Users
            </NavLink>
          )}
        </nav>

        {domains.length > 0 && (
          <div className="sidebar-section">
            <span className="sidebar-section-title">My domains</span>
            <div className="sidebar-domain-list">
              {domains.map((d) => (
                <NavLink key={d.domain_id} to={`/domains/${d.domain_id}`} className={domainLinkClass}>
                  <span className="sidebar-domain-name">{d.domain_name}</span>
                  <Badge tone="neutral">{ROLE_LABELS[d.role] ?? d.role}</Badge>
                </NavLink>
              ))}
            </div>
          </div>
        )}

        <div className="sidebar-footer">
          <select
            className="theme-select"
            value={theme}
            onChange={(e) => setTheme(e.target.value as 'light' | 'dark' | 'system')}
            aria-label="Theme"
          >
            <option value="system">System theme</option>
            <option value="light">Light</option>
            <option value="dark">Dark</option>
          </select>
          <div className="sidebar-user">
            <span className="sidebar-user-email" title={user?.email}>
              {user?.email}
            </span>
            {user?.is_platform_admin && <Badge tone="info">Platform admin</Badge>}
          </div>
          <button className="btn btn-ghost sidebar-logout" onClick={logout}>
            Log out
          </button>
        </div>
      </aside>
      <main className="app-content">
        <Outlet />
      </main>
    </div>
  )
}
