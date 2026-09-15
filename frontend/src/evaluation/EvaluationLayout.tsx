import { NavLink, Outlet, useParams } from 'react-router-dom'

export function EvaluationLayout() {
  const { domainId } = useParams<{ domainId: string }>()

  return (
    <div>
      <div className="tabs">
        <NavLink
          to={`/domains/${domainId}/evaluation/dashboard`}
          className={({ isActive }) => (isActive ? 'tab active' : 'tab')}
        >
          Dashboard
        </NavLink>
        <NavLink
          to={`/domains/${domainId}/evaluation/moderation`}
          className={({ isActive }) => (isActive ? 'tab active' : 'tab')}
        >
          Moderation queue
        </NavLink>
        <NavLink
          to={`/domains/${domainId}/evaluation/golden-qa`}
          className={({ isActive }) => (isActive ? 'tab active' : 'tab')}
        >
          Golden QA
        </NavLink>
      </div>
      <Outlet />
    </div>
  )
}
