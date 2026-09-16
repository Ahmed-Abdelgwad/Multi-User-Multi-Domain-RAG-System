import { useRef, useState, type FormEvent } from 'react'
import { useQuery } from '@tanstack/react-query'
import { listDomains } from '../api/domains'
import { getQueryEvaluation, submitQuery } from '../api/query'
import { ApiError } from '../api/client'
import type { EvaluationDetailResponse, EvaluationStatus, QueryResponse } from '../api/types'
import { Badge } from '../components/Badge'
import { EmptyState } from '../components/EmptyState'
import { Spinner } from '../components/Spinner'

const TERMINAL: EvaluationStatus[] = ['completed', 'failed', 'skipped']
const EVAL_POLL_MS = 2000
const EVAL_POLL_TIMEOUT_MS = 30000
const DIMENSIONS = ['faithfulness', 'relevance', 'completeness', 'citation_accuracy'] as const

interface Turn {
  id: string
  question: string
  status: 'pending' | 'done' | 'error'
  result?: QueryResponse
  error?: string
  evaluation?: EvaluationDetailResponse
  evaluationTimedOut?: boolean
}

export function QueryPage() {
  const domainsQuery = useQuery({ queryKey: ['domains'], queryFn: listDomains })
  const [selectedDomainIds, setSelectedDomainIds] = useState<string[]>([])
  const [question, setQuestion] = useState('')
  const [turns, setTurns] = useState<Turn[]>([])
  const [isSubmitting, setIsSubmitting] = useState(false)
  const mountedRef = useRef(true)

  function updateTurn(id: string, patch: Partial<Turn>) {
    if (!mountedRef.current) return
    setTurns((prev) => prev.map((t) => (t.id === id ? { ...t, ...patch } : t)))
  }

  function pollEvaluation(turnId: string, queryLogId: string, elapsedMs = 0) {
    getQueryEvaluation(queryLogId).then((detail) => {
      updateTurn(turnId, { evaluation: detail })
      if (!TERMINAL.includes(detail.status)) {
        if (elapsedMs >= EVAL_POLL_TIMEOUT_MS) {
          updateTurn(turnId, { evaluationTimedOut: true })
          return
        }
        setTimeout(() => pollEvaluation(turnId, queryLogId, elapsedMs + EVAL_POLL_MS), EVAL_POLL_MS)
      }
    })
  }

  function toggleDomain(domainId: string) {
    setSelectedDomainIds((prev) =>
      prev.includes(domainId) ? prev.filter((id) => id !== domainId) : [...prev, domainId],
    )
  }

  function handleSubmit(event: FormEvent) {
    event.preventDefault()
    const askedQuestion = question.trim()
    if (!askedQuestion || selectedDomainIds.length === 0) return

    const turnId = crypto.randomUUID()
    setTurns((prev) => [...prev, { id: turnId, question: askedQuestion, status: 'pending' }])
    setQuestion('')
    setIsSubmitting(true)

    submitQuery(askedQuestion, selectedDomainIds)
      .then((data) => {
        updateTurn(turnId, { status: 'done', result: data })
        pollEvaluation(turnId, data.query_log_id)
      })
      .catch((err) => {
        updateTurn(turnId, { status: 'error', error: err instanceof ApiError ? err.message : 'Could not run query' })
      })
      .finally(() => setIsSubmitting(false))
  }

  const activeDomains = domainsQuery.data?.filter((d) => !d.is_archived) ?? []

  return (
    <div className="chat-page">
      <div className="chat-domain-bar">
        <span className="muted">Domains:</span>
        {domainsQuery.isLoading && <Spinner />}
        {activeDomains.map((domain) => (
          <button
            key={domain.id}
            type="button"
            className={selectedDomainIds.includes(domain.id) ? 'domain-pill selected' : 'domain-pill'}
            onClick={() => toggleDomain(domain.id)}
          >
            {domain.name}
          </button>
        ))}
        {activeDomains.length === 0 && !domainsQuery.isLoading && <span className="muted">No domains available.</span>}
      </div>

      <div className="chat-thread">
        {turns.length === 0 && (
          <EmptyState
            title="Ask something"
            description="Pick at least one domain above, then ask a question grounded in its ingested documents."
          />
        )}
        {turns.map((turn) => (
          <TurnBubbles key={turn.id} turn={turn} />
        ))}
      </div>

      <form onSubmit={handleSubmit} className="chat-composer">
        <textarea
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault()
              handleSubmit(e)
            }
          }}
          rows={2}
          placeholder={selectedDomainIds.length === 0 ? 'Select a domain first...' : 'Ask a question...'}
          disabled={selectedDomainIds.length === 0}
        />
        <button
          type="submit"
          className="btn btn-primary"
          disabled={isSubmitting || selectedDomainIds.length === 0 || !question.trim()}
        >
          Send
        </button>
      </form>
    </div>
  )
}

function TurnBubbles({ turn }: { turn: Turn }) {
  return (
    <div className="chat-turn">
      <div className="chat-bubble chat-bubble-user">{turn.question}</div>

      <div className="chat-bubble chat-bubble-assistant">
        {turn.status === 'pending' && <Spinner />}
        {turn.status === 'error' && <p className="chat-error">{turn.error}</p>}
        {turn.status === 'done' && turn.result && (
          <>
            <div className="query-result-header">
              <Badge tone="info">{turn.result.route}</Badge>
              <span className={turn.result.low_confidence ? 'confidence low' : 'confidence'}>
                confidence {(turn.result.confidence * 100).toFixed(0)}%
              </span>
              {turn.result.low_confidence && <Badge tone="warning">Low confidence</Badge>}
            </div>
            <p className="answer-text">{turn.result.answer}</p>

            {turn.result.entities.length > 0 && (
              <div className="entities">
                {turn.result.entities.map(([text, label], i) => (
                  <Badge key={i} tone="neutral">
                    {text} ({label})
                  </Badge>
                ))}
              </div>
            )}

            <details className="chat-sources">
              <summary>{turn.result.sources.length} source{turn.result.sources.length === 1 ? '' : 's'}</summary>
              <ul className="sources-list">
                {turn.result.sources.map((source) => (
                  <li key={source.chunk_id}>
                    <Badge tone={source.content_type === 'table' ? 'info' : 'neutral'}>{source.content_type}</Badge>{' '}
                    {source.domain_name}
                    {source.score !== null && <span className="muted"> -- score {source.score.toFixed(2)}</span>}
                  </li>
                ))}
              </ul>
            </details>

            <EvaluationPanel evaluation={turn.evaluation} timedOut={turn.evaluationTimedOut} />
          </>
        )}
      </div>
    </div>
  )
}

function EvaluationPanel({ evaluation, timedOut }: { evaluation?: EvaluationDetailResponse; timedOut?: boolean }) {
  if (!evaluation) {
    return <p className="muted chat-eval-pending">Judge evaluation queued...</p>
  }
  if (!TERMINAL.includes(evaluation.status)) {
    return (
      <p className="muted chat-eval-pending">
        {timedOut ? 'Still pending after 30s -- check back later.' : `Judge evaluation in progress (${evaluation.status})...`}
      </p>
    )
  }
  if (evaluation.status === 'skipped') {
    return <p className="muted chat-eval-pending">Evaluation skipped: {evaluation.error_message}</p>
  }
  if (evaluation.status === 'failed') {
    return <p className="chat-error">Evaluation failed: {evaluation.error_message}</p>
  }
  return (
    <div className="dimension-grid chat-eval-grid">
      {DIMENSIONS.map((dim) => (
        <div key={dim} className="dimension-cell">
          <span className="muted">{dim.replace('_', ' ')}</span>
          <strong>{evaluation[dim] !== null ? evaluation[dim]!.toFixed(2) : '--'}</strong>
        </div>
      ))}
      {evaluation.flagged && <Badge tone="danger">Flagged for review</Badge>}
    </div>
  )
}
