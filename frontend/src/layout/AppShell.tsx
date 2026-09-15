import { NavLink, Outlet } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { Button } from '../components/Button'

export function AppShell() {
  const { user, logout } = useAuth()

  return (
    <div className="app-shell">
      <header className="app-topbar">
        <span className="app-title">RAG Console</span>
        <div className="app-topbar-right">
          {user && (
            <span className="app-user">
              {user.email}
              {user.is_platform_admin ? ' (platform admin)' : ''}
            </span>
          )}
          <Button variant="ghost" onClick={logout}>
            Log out
          </Button>
        </div>
      </header>
      <div className="app-body">
        <nav className="app-nav">
          <NavLink to="/domains" className={({ isActive }) => (isActive ? 'active' : undefined)}>
            Domains
          </NavLink>
          <NavLink to="/query" className={({ isActive }) => (isActive ? 'active' : undefined)}>
            Query
          </NavLink>
        </nav>
        <main className="app-content">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
