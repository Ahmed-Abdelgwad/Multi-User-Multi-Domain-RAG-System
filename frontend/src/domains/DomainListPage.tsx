import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { createDomain, deleteAllArchivedDomains, listDomains } from '../api/domains'
import { useAuth } from '../auth/AuthContext'
import { ApiError } from '../api/client'
import { useToast } from '../components/ToastProvider'
import { Badge } from '../components/Badge'
import { Button } from '../components/Button'
import { EmptyState } from '../components/EmptyState'
import { ErrorBanner } from '../components/ErrorBanner'
import { Modal } from '../components/Modal'
import { SkeletonTable } from '../components/Skeleton'
import type { DomainResponse, DomainRole } from '../api/types'

const ROLE_LABELS: Record<DomainRole, string> = {
  reader: 'Reader',
  contributor: 'Contributor',
  domain_admin: 'Admin',
}

export function DomainListPage() {
  const { user, domains: myMemberships, refreshDomains } = useAuth()
  const queryClient = useQueryClient()
  const { addToast } = useToast()
  const { data: domains, isLoading, error } = useQuery({ queryKey: ['domains'], queryFn: listDomains })
  const [showCreate, setShowCreate] = useState(false)
  const [showDeleteAllConfirm, setShowDeleteAllConfirm] = useState(false)
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [formError, setFormError] = useState<string | null>(null)

  const createMutation = useMutation({
    mutationFn: () => createDomain({ name, description: description || undefined }),
    onSuccess: (created) => {
      queryClient.invalidateQueries({ queryKey: ['domains'] })
      refreshDomains()
      setShowCreate(false)
      setName('')
      setDescription('')
      addToast(`Domain "${created.name}" created`, 'success')
    },
    onError: (err) => setFormError(err instanceof ApiError ? err.message : 'Could not create domain'),
  })

  const deleteAllMutation = useMutation({
    mutationFn: () => deleteAllArchivedDomains(),
    onSuccess: (deletedIds) => {
      queryClient.invalidateQueries({ queryKey: ['domains'] })
      refreshDomains()
      setShowDeleteAllConfirm(false)
      addToast(
        deletedIds.length === 0 ? 'No archived domains to delete' : `Deleted ${deletedIds.length} archived domain(s)`,
        'success',
      )
    },
    onError: (err) => {
      addToast(err instanceof ApiError ? err.message : 'Could not delete archived domains', 'error')
      setShowDeleteAllConfirm(false)
    },
  })

  if (isLoading) {
    return (
      <div>
        <h1>Domains</h1>
        <SkeletonTable />
      </div>
    )
  }

  const roleByDomainId = new Map(myMemberships.map((m) => [m.domain_id, m.role]))
  const myDomains = (domains ?? []).filter((d) => roleByDomainId.has(d.id))
  const otherDomains = (domains ?? []).filter((d) => !roleByDomainId.has(d.id))

  const hasNoAccessAtAll = myDomains.length === 0 && !user?.is_platform_admin
  const hasArchivedDomains = (domains ?? []).some((d) => d.is_archived)

  return (
    <div>
      <div className="page-header">
        <h1>Domains</h1>
        <div className="button-row">
          {user?.is_platform_admin && hasArchivedDomains && (
            <Button variant="danger" onClick={() => setShowDeleteAllConfirm(true)}>
              Delete all archived
            </Button>
          )}
          {user?.is_platform_admin && <Button onClick={() => setShowCreate(true)}>Create domain</Button>}
        </div>
      </div>
      {error && <ErrorBanner message={error instanceof ApiError ? error.message : 'Could not load domains'} />}

      {showDeleteAllConfirm && (
        <Modal title="Delete all archived domains?" onClose={() => setShowDeleteAllConfirm(false)}>
          <p>
            This permanently deletes every archived domain and everything in it -- documents, chunks, graph data,
            config, roles, and related query history. Active (non-archived) domains are left untouched. This cannot
            be undone.
          </p>
          <div className="form-actions">
            <Button
              variant="ghost"
              onClick={() => setShowDeleteAllConfirm(false)}
              disabled={deleteAllMutation.isPending}
            >
              Cancel
            </Button>
            <Button variant="danger" onClick={() => deleteAllMutation.mutate()} disabled={deleteAllMutation.isPending}>
              {deleteAllMutation.isPending ? 'Deleting...' : 'Delete all archived'}
            </Button>
          </div>
        </Modal>
      )}

      {hasNoAccessAtAll ? (
        <EmptyState
          title="You don't have access to any domains yet"
          description="Domains are isolated on purpose -- a domain admin has to grant you a role before you can see or query anything in one."
        >
          <p className="muted">
            Share your account with a domain admin so they can add you:
            <br />
            <strong>{user?.email}</strong>
          </p>
        </EmptyState>
      ) : (
        <>
          <h2 className="section-title">My domains</h2>
          {myDomains.length === 0 && <p className="muted">You don't have a role in any domain yet.</p>}
          {myDomains.length > 0 && (
            <DomainTable domains={myDomains} roleByDomainId={roleByDomainId} />
          )}

          {user?.is_platform_admin && otherDomains.length > 0 && (
            <>
              <h2 className="section-title">All domains</h2>
              <p className="muted">Visible to you as a platform admin for oversight -- this alone doesn't grant you read access to their content.</p>
              <DomainTable domains={otherDomains} roleByDomainId={roleByDomainId} />
            </>
          )}
        </>
      )}

      {showCreate && (
        <Modal title="Create domain" onClose={() => setShowCreate(false)}>
          {formError && <ErrorBanner message={formError} />}
          <form
            onSubmit={(e) => {
              e.preventDefault()
              setFormError(null)
              createMutation.mutate()
            }}
          >
            <label>
              Name
              <input value={name} onChange={(e) => setName(e.target.value)} required autoFocus />
            </label>
            <label>
              Description
              <input value={description} onChange={(e) => setDescription(e.target.value)} />
            </label>
            <Button type="submit" disabled={createMutation.isPending}>
              {createMutation.isPending ? 'Creating...' : 'Create'}
            </Button>
          </form>
        </Modal>
      )}
    </div>
  )
}

function DomainTable({
  domains,
  roleByDomainId,
}: {
  domains: DomainResponse[]
  roleByDomainId: Map<string, DomainRole>
}) {
  return (
    <table className="table">
      <thead>
        <tr>
          <th>Name</th>
          <th>Your role</th>
          <th>Description</th>
          <th>Status</th>
          <th>Created</th>
        </tr>
      </thead>
      <tbody>
        {domains.map((domain) => {
          const role = roleByDomainId.get(domain.id)
          return (
            <tr key={domain.id}>
              <td>
                <Link to={`/domains/${domain.id}`}>{domain.name}</Link>
              </td>
              <td>{role ? <Badge tone="neutral">{ROLE_LABELS[role]}</Badge> : <span className="muted">--</span>}</td>
              <td>{domain.description ?? '--'}</td>
              <td>
                {domain.is_archived ? <Badge tone="warning">Archived</Badge> : <Badge tone="success">Active</Badge>}
              </td>
              <td>{new Date(domain.created_at).toLocaleString()}</td>
            </tr>
          )
        })}
      </tbody>
    </table>
  )
}
