import { Navigate, Outlet, useLocation } from 'react-router-dom'
import { useAuth } from './AuthContext'
import { Spinner } from '../components/Spinner'

export function RequireAuth() {
  const { token, isLoading } = useAuth()
  const location = useLocation()

  if (token && isLoading) return <Spinner />
  if (!token) return <Navigate to="/login" state={{ from: location.pathname }} replace />
  return <Outlet />
}
