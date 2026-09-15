import { useState } from 'react'
import { useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { getModerationQueue, overrideEvaluation, setEvaluationVerdict } from '../api/evaluation'
import { ApiError } from '../api/client'
import type { ModerationQueueItemResponse } from '../api/types'
import { Badge } from '../components/Badge'
import { Button } from '../components/Button'
import { ErrorBanner } from '../components/ErrorBanner'
import { Modal } from '../components/Modal'
import { Spinner } from '../components/Spinner'

const DIMENSIONS = ['faithfulness', 'relevance', 'completeness', 'citation_accuracy'] as const

export function ModerationQueuePage() {
  const { domainId } = useParams<{ domainId: string }>()
  const queryClient = useQueryClient()
  const [overrideTarget, setOverrideTarget] = useState<ModerationQueueItemResponse | null>(null)

  const queueQuery = useQuery({
    queryKey: ['moderation-queue', domainId],
    queryFn: () => getModerationQueue(domainId!),
    enabled: Boolean(domainId),
  })

  const verdictMutation = useMutation({
    mutationFn: ({ queryLogId, verdict }: { queryLogId: string; verdict: 'accepted' | 'rejected' }) =>
      setEvaluationVerdict(domainId!, queryLogId, { verdict, rationale: `${verdict} via console` }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['moderation-queue', domainId] }),
  })

  if (queueQuery.isLoading) return <Spinner />
  if (queueQuery.error) {
    return (
      <ErrorBanner
        message={queueQuery.error instanceof ApiError ? queueQuery.error.message : 'Could not load moderation queue'}
      />
    )
  }

  return (
    <div>
      <h1>Moderation queue</h1>
      {queueQuery.data?.length === 0 && <p className="muted">Nothing flagged right now.</p>}
      <div className="moderation-list">
        {queueQuery.data?.map((item) => (
          <div key={item.query_log_id} className="moderation-card">
            <div className="moderation-card-header">
              <Badge tone="danger">Flagged</Badge>
              <span className="muted">{new Date(item.query_created_at).toLocaleString()}</span>
              {item.human_verdict && (
                <Badge tone={item.human_verdict === 'accepted' ? 'success' : 'danger'}>{item.human_verdict}</Badge>
              )}
            </div>
            <p>
              <strong>Q:</strong> {item.query}
            </p>
            <p>
              <strong>A:</strong> {item.answer}
            </p>
            <div className="dimension-grid">
              {DIMENSIONS.map((dim) => (
                <div key={dim} className="dimension-cell">
                  <span className="muted">{dim.replace('_', ' ')}</span>
                  <strong>{item[dim] !== null ? item[dim]!.toFixed(2) : '--'}</strong>
                </div>
              ))}
            </div>
            <div className="moderation-actions">
              <Button variant="ghost" onClick={() => setOverrideTarget(item)}>
                Override scores
              </Button>
              <Button
                variant="ghost"
                onClick={() => verdictMutation.mutate({ queryLogId: item.query_log_id, verdict: 'accepted' })}
                disabled={verdictMutation.isPending}
              >
                Accept
              </Button>
              <Button
                variant="danger"
                onClick={() => verdictMutation.mutate({ queryLogId: item.query_log_id, verdict: 'rejected' })}
                disabled={verdictMutation.isPending}
              >
                Reject
              </Button>
            </div>
          </div>
        ))}
      </div>

      {overrideTarget && (
        <OverrideModal
          domainId={domainId!}
          item={overrideTarget}
          onClose={() => setOverrideTarget(null)}
          onSuccess={() => {
            setOverrideTarget(null)
            queryClient.invalidateQueries({ queryKey: ['moderation-queue', domainId] })
          }}
        />
      )}
    </div>
  )
}

function OverrideModal({
  domainId,
  item,
  onClose,
  onSuccess,
}: {
  domainId: string
  item: ModerationQueueItemResponse
  onClose: () => void
  onSuccess: () => void
}) {
  const [scores, setScores] = useState({
    faithfulness: item.faithfulness ?? 0,
    relevance: item.relevance ?? 0,
    completeness: item.completeness ?? 0,
    citation_accuracy: item.citation_accuracy ?? 0,
  })
  const [rationale, setRationale] = useState('')
  const [error, setError] = useState<string | null>(null)

  const mutation = useMutation({
    mutationFn: () => overrideEvaluation(domainId, item.query_log_id, { ...scores, rationale }),
    onSuccess,
    onError: (err) => setError(err instanceof ApiError ? err.message : 'Could not override evaluation'),
  })

  return (
    <Modal title="Override evaluation" onClose={onClose}>
      {error && <ErrorBanner message={error} />}
      <form
        onSubmit={(e) => {
          e.preventDefault()
          setError(null)
          mutation.mutate()
        }}
      >
        {DIMENSIONS.map((dim) => (
          <label key={dim}>
            {dim.replace('_', ' ')}
            <input
              type="number"
              min={0}
              max={1}
              step={0.05}
              value={scores[dim]}
              onChange={(e) => setScores((prev) => ({ ...prev, [dim]: Number(e.target.value) }))}
              required
            />
          </label>
        ))}
        <label>
          Rationale
          <textarea value={rationale} onChange={(e) => setRationale(e.target.value)} rows={3} required />
        </label>
        <Button type="submit" disabled={mutation.isPending}>
          {mutation.isPending ? 'Saving...' : 'Save override'}
        </Button>
      </form>
    </Modal>
  )
}
