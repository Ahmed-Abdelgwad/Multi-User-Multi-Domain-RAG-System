import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { archiveDomain, assignRole, getDomain, listDomainRoles, revokeRole } from '../api/domains'
import { useAuth } from '../auth/AuthContext'
import { ApiError } from '../api/client'
import { useToast } from '../components/ToastProvider'
import type { DomainRole, UserResponse } from '../api/types'
import { Badge } from '../components/Badge'
import { Button } from '../components/Button'
import { ErrorBanner } from '../components/ErrorBanner'
import { Spinner } from '../components/Spinner'
import { UserSearchCombobox } from '../components/UserSearchCombobox'

const ROLE_OPTIONS: DomainRole[] = ['reader', 'contributor', 'domain_admin']

export function DomainDetailPage() {
  const { domainId } = useParams<{ domainId: string }>()
  const { user, domains: myDomains } = useAuth()
  const queryClient = useQueryClient()
  const [tab, setTab] = useState<'overview' | 'roles'>('overview')

  const domainQuery = useQuery({
    queryKey: ['domain', domainId],
    queryFn: () => getDomain(domainId!),
    enabled: Boolean(domainId),
  })

  const myRole = myDomains.find((d) => d.domain_id === domainId)?.role
  const isDomainAdmin = Boolean(user?.is_platform_admin || myRole === 'domain_admin')

  const { addToast } = useToast()

  const archiveMutation = useMutation({
    mutationFn: () => archiveDomain(domainId!),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['domain', domainId] })
      addToast('Domain archived', 'success')
    },
  })

  if (domainQuery.isLoading) return <Spinner />
  if (domainQuery.error) {
    return (
      <ErrorBanner
        message={domainQuery.error instanceof ApiError ? domainQuery.error.message : 'Could not load domain'}
      />
    )
  }
  const domain = domainQuery.data!

  return (
    <div>
      <div className="page-header">
        <h1>
          {domain.name} {domain.is_archived && <Badge tone="warning">Archived</Badge>}
        </h1>
        {isDomainAdmin && !domain.is_archived && (
          <Button variant="danger" onClick={() => archiveMutation.mutate()} disabled={archiveMutation.isPending}>
            {archiveMutation.isPending ? 'Archiving...' : 'Archive domain'}
          </Button>
        )}
      </div>
      <p className="muted">{domain.description ?? 'No description.'}</p>

      <div className="tabs">
        <button className={tab === 'overview' ? 'tab active' : 'tab'} onClick={() => setTab('overview')}>
          Overview
        </button>
        {isDomainAdmin && (
          <button className={tab === 'roles' ? 'tab active' : 'tab'} onClick={() => setTab('roles')}>
            Roles
          </button>
        )}
        <Link className="tab" to={`/domains/${domain.id}/documents`}>
          Documents
        </Link>
        {isDomainAdmin && (
          <Link className="tab" to={`/domains/${domain.id}/evaluation`}>
            Evaluation
          </Link>
        )}
      </div>

      {tab === 'overview' && (
        <dl className="detail-list">
          <dt>Created</dt>
          <dd>{new Date(domain.created_at).toLocaleString()}</dd>
          <dt>Domain ID</dt>
          <dd>
            <code>{domain.id}</code>
          </dd>
        </dl>
      )}

      {tab === 'roles' && isDomainAdmin && <RolesTab domainId={domain.id} />}
    </div>
  )
}

function RolesTab({ domainId }: { domainId: string }) {
  const queryClient = useQueryClient()
  const { addToast } = useToast()
  const [selectedUser, setSelectedUser] = useState<UserResponse | null>(null)
  const [role, setRole] = useState<DomainRole>('reader')
  const [formError, setFormError] = useState<string | null>(null)

  const rolesQuery = useQuery({ queryKey: ['domain-roles', domainId], queryFn: () => listDomainRoles(domainId) })

  const assignMutation = useMutation({
    mutationFn: () => assignRole(domainId, { user_id: selectedUser!.id, role }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['domain-roles', domainId] })
      addToast(`${selectedUser!.email} granted ${role}`, 'success')
      setSelectedUser(null)
    },
    onError: (err) => setFormError(err instanceof ApiError ? err.message : 'Could not assign role'),
  })

  const revokeMutation = useMutation({
    mutationFn: (targetUserId: string) => revokeRole(domainId, targetUserId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['domain-roles', domainId] })
      addToast('Role revoked', 'success')
    },
  })

  if (rolesQuery.isLoading) return <Spinner />

  return (
    <div>
      <table className="table">
        <thead>
          <tr>
            <th>User</th>
            <th>Role</th>
            <th>Granted</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {rolesQuery.data?.map((r) => (
            <tr key={r.user_id}>
              <td>{r.user_email ?? <code>{r.user_id}</code>}</td>
              <td>
                <Badge tone="info">{r.role}</Badge>
              </td>
              <td>{new Date(r.granted_at).toLocaleString()}</td>
              <td>
                <Button
                  variant="ghost"
                  onClick={() => revokeMutation.mutate(r.user_id)}
                  disabled={revokeMutation.isPending}
                >
                  Revoke
                </Button>
              </td>
            </tr>
          ))}
          {rolesQuery.data?.length === 0 && (
            <tr>
              <td colSpan={4}>No roles assigned yet.</td>
            </tr>
          )}
        </tbody>
      </table>

      <h3>Assign role</h3>
      {formError && <ErrorBanner message={formError} />}
      <form
        className="inline-form"
        onSubmit={(e) => {
          e.preventDefault()
          setFormError(null)
          assignMutation.mutate()
        }}
      >
        <label>
          User
          {selectedUser ? (
            <div className="selected-user-chip">
              <span>
                {selectedUser.first_name} {selectedUser.last_name} &lt;{selectedUser.email}&gt;
              </span>
              <button type="button" className="chip-clear" onClick={() => setSelectedUser(null)} aria-label="Clear">
                ×
              </button>
            </div>
          ) : (
            <UserSearchCombobox domainId={domainId} onSelect={setSelectedUser} />
          )}
        </label>
        <label>
          Role
          <select value={role} onChange={(e) => setRole(e.target.value as DomainRole)}>
            {ROLE_OPTIONS.map((r) => (
              <option key={r} value={r}>
                {r}
              </option>
            ))}
          </select>
        </label>
        <Button type="submit" disabled={assignMutation.isPending || !selectedUser}>
          {assignMutation.isPending ? 'Assigning...' : 'Assign'}
        </Button>
      </form>
    </div>
  )
}
