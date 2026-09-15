import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { createDomain, listDomains } from '../api/domains'
import { useAuth } from '../auth/AuthContext'
import { ApiError } from '../api/client'
import { Badge } from '../components/Badge'
import { Button } from '../components/Button'
import { ErrorBanner } from '../components/ErrorBanner'
import { Modal } from '../components/Modal'
import { Spinner } from '../components/Spinner'

export function DomainListPage() {
  const { user } = useAuth()
  const queryClient = useQueryClient()
  const { data: domains, isLoading, error } = useQuery({ queryKey: ['domains'], queryFn: listDomains })
  const [showCreate, setShowCreate] = useState(false)
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [formError, setFormError] = useState<string | null>(null)

  const createMutation = useMutation({
    mutationFn: () => createDomain({ name, description: description || undefined }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['domains'] })
      setShowCreate(false)
      setName('')
      setDescription('')
    },
    onError: (err) => setFormError(err instanceof ApiError ? err.message : 'Could not create domain'),
  })

  if (isLoading) return <Spinner />

  return (
    <div>
      <div className="page-header">
        <h1>Domains</h1>
        {user?.is_platform_admin && <Button onClick={() => setShowCreate(true)}>Create domain</Button>}
      </div>
      {error && <ErrorBanner message={error instanceof ApiError ? error.message : 'Could not load domains'} />}
      <table className="table">
        <thead>
          <tr>
            <th>Name</th>
            <th>Description</th>
            <th>Status</th>
            <th>Created</th>
          </tr>
        </thead>
        <tbody>
          {domains?.map((domain) => (
            <tr key={domain.id}>
              <td>
                <Link to={`/domains/${domain.id}`}>{domain.name}</Link>
              </td>
              <td>{domain.description ?? '--'}</td>
              <td>
                {domain.is_archived ? <Badge tone="warning">Archived</Badge> : <Badge tone="success">Active</Badge>}
              </td>
              <td>{new Date(domain.created_at).toLocaleString()}</td>
            </tr>
          ))}
          {domains?.length === 0 && (
            <tr>
              <td colSpan={4}>No domains yet.</td>
            </tr>
          )}
        </tbody>
      </table>

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
