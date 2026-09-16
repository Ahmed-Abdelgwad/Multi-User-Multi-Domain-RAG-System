import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { listUsers, setPlatformAdmin } from '../api/users'
import { useAuth } from '../auth/AuthContext'
import { ApiError } from '../api/client'
import { useToast } from '../components/ToastProvider'
import { Badge } from '../components/Badge'
import { Button } from '../components/Button'
import { EmptyState } from '../components/EmptyState'
import { ErrorBanner } from '../components/ErrorBanner'
import { SkeletonTable } from '../components/Skeleton'

export function UsersPage() {
  const { user: currentUser } = useAuth()
  const queryClient = useQueryClient()
  const { addToast } = useToast()
  const [error, setError] = useState<string | null>(null)

  const usersQuery = useQuery({
    queryKey: ['users'],
    queryFn: () => listUsers(100),
    enabled: Boolean(currentUser?.is_platform_admin),
  })

  const toggleMutation = useMutation({
    mutationFn: ({ userId, next }: { userId: string; next: boolean }) => setPlatformAdmin(userId, next),
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: ['users'] })
      addToast(variables.next ? 'Granted platform admin' : 'Revoked platform admin', 'success')
    },
    onError: (err) => setError(err instanceof ApiError ? err.message : 'Could not update admin status'),
  })

  if (!currentUser?.is_platform_admin) {
    return (
      <EmptyState
        title="Platform admins only"
        description="This page manages who else can administer the whole platform. Ask a platform admin if you need access here."
      />
    )
  }

  return (
    <div>
      <h1>Users</h1>
      <p className="muted">
        Grant or revoke platform admin. A platform admin can create domains and manage every user's admin status here
        -- this is the only place that capability changes hands from now on.
      </p>
      {error && <ErrorBanner message={error} />}
      {usersQuery.isLoading && <SkeletonTable />}
      {usersQuery.data && (
        <table className="table">
          <thead>
            <tr>
              <th>Name</th>
              <th>Email</th>
              <th>Platform admin</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {usersQuery.data.map((u) => (
              <tr key={u.id}>
                <td>
                  {u.first_name} {u.last_name}
                </td>
                <td>{u.email}</td>
                <td>
                  {u.is_platform_admin ? <Badge tone="info">Admin</Badge> : <Badge tone="neutral">Standard</Badge>}
                </td>
                <td>
                  <Button
                    variant={u.is_platform_admin ? 'danger' : 'ghost'}
                    disabled={u.id === currentUser.id || toggleMutation.isPending}
                    title={u.id === currentUser.id ? "You can't change your own status" : undefined}
                    onClick={() => toggleMutation.mutate({ userId: u.id, next: !u.is_platform_admin })}
                  >
                    {u.is_platform_admin ? 'Revoke admin' : 'Make admin'}
                  </Button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}
