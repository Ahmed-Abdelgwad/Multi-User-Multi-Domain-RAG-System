import { useEffect, useRef, useState, type FormEvent } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { listDomains } from '../api/domains'
import { getQueryEvaluation, submitQuery } from '../api/query'
import { ApiError } from '../api/client'
import type { EvaluationDetailResponse, EvaluationStatus, QueryResponse } from '../api/types'
import { Badge } from '../components/Badge'
import { Button } from '../components/Button'
import { ErrorBanner } from '../components/ErrorBanner'
import { Spinner } from '../components/Spinner'

const TERMINAL: EvaluationStatus[] = ['completed', 'failed', 'skipped']
const EVAL_POLL_MS = 2000
const EVAL_POLL_TIMEOUT_MS = 30000

const DIMENSIONS = ['faithfulness', 'relevance', 'completeness', 'citation_accuracy'] as const

export function QueryPage() {
  const domainsQuery = useQuery({ queryKey: ['domains'], queryFn: listDomains })
  const [selectedDomainIds, setSelectedDomainIds] = useState<string[]>([])
  const [question, setQuestion] = useState('')
  const [result, setResult] = useState<QueryResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [evaluation, setEvaluation] = useState<EvaluationDetailResponse | null>(null)
  const [evaluationTimedOut, setEvaluationTimedOut] = useState(false)
  const activePollRef = useRef<string | null>(null)

  useEffect(() => () => {
    activePollRef.current = null
  }, [])

  function pollEvaluation(queryLogId: string, elapsedMs = 0) {
    getQueryEvaluation(queryLogId).then((detail) => {
      if (activePollRef.current !== queryLogId) return // superseded by a newer question
      setEvaluation(detail)
      if (!TERMINAL.includes(detail.status)) {
        if (elapsedMs >= EVAL_POLL_TIMEOUT_MS) {
          setEvaluationTimedOut(true)
          return
        }
        setTimeout(() => pollEvaluation(queryLogId, elapsedMs + EVAL_POLL_MS), EVAL_POLL_MS)
      }
    })
  }

  const submitMutation = useMutation({
    mutationFn: () => submitQuery(question, selectedDomainIds),
    onSuccess: (data) => {
      setResult(data)
      setEvaluation(null)
      setEvaluationTimedOut(false)
      activePollRef.current = data.query_log_id
      pollEvaluation(data.query_log_id)
    },
    onError: (err) => setError(err instanceof ApiError ? err.message : 'Could not run query'),
  })

  function toggleDomain(domainId: string) {
    setSelectedDomainIds((prev) =>
      prev.includes(domainId) ? prev.filter((id) => id !== domainId) : [...prev, domainId],
    )
  }

  function handleSubmit(event: FormEvent) {
    event.preventDefault()
    setError(null)
    submitMutation.mutate()
  }

  const activeDomains = domainsQuery.data?.filter((d) => !d.is_archived) ?? []

  return (
    <div>
      <h1>Query</h1>
      <form onSubmit={handleSubmit} className="query-form">
        <fieldset>
          <legend>Domains</legend>
          {domainsQuery.isLoading && <Spinner />}
          <div className="domain-checkboxes">
            {activeDomains.map((domain) => (
              <label key={domain.id} className="checkbox-label">
                <input
                  type="checkbox"
                  checked={selectedDomainIds.includes(domain.id)}
                  onChange={() => toggleDomain(domain.id)}
                />
                {domain.name}
              </label>
            ))}
            {activeDomains.length === 0 && !domainsQuery.isLoading && <p className="muted">No domains available.</p>}
          </div>
        </fieldset>
        <label>
          Question
          <textarea value={question} onChange={(e) => setQuestion(e.target.value)} rows={3} required />
        </label>
        <Button type="submit" disabled={submitMutation.isPending || selectedDomainIds.length === 0}>
          {submitMutation.isPending ? 'Asking...' : 'Ask'}
        </Button>
      </form>

      {error && <ErrorBanner message={error} />}

      {result && (
        <div className="query-result">
          <div className="query-result-header">
            <Badge tone="info">{result.route}</Badge>
            <span className={result.low_confidence ? 'confidence low' : 'confidence'}>
              confidence {(result.confidence * 100).toFixed(0)}%
            </span>
            {result.low_confidence && <Badge tone="warning">Low confidence</Badge>}
          </div>
          <p className="answer-text">{result.answer}</p>

          {result.entities.length > 0 && (
            <div className="entities">
              <h3>Detected entities</h3>
              {result.entities.map(([text, label], i) => (
                <Badge key={i} tone="neutral">
                  {text} ({label})
                </Badge>
              ))}
            </div>
          )}

          <h3>Sources</h3>
          <ul className="sources-list">
            {result.sources.map((source) => (
              <li key={source.chunk_id}>
                <Badge tone={source.content_type === 'table' ? 'info' : 'neutral'}>{source.content_type}</Badge>{' '}
                {source.domain_name}
                {source.score !== null && <span className="muted"> -- score {source.score.toFixed(2)}</span>}
              </li>
            ))}
          </ul>

          <h3>Evaluation</h3>
          {!evaluation && <Spinner />}
          {evaluation && !TERMINAL.includes(evaluation.status) && !evaluationTimedOut && (
            <p className="muted">Judge evaluation in progress ({evaluation.status})...</p>
          )}
          {evaluation && evaluationTimedOut && !TERMINAL.includes(evaluation.status) && (
            <p className="muted">Still pending after 30s -- check back later.</p>
          )}
          {evaluation && evaluation.status === 'completed' && (
            <div className="dimension-grid">
              {DIMENSIONS.map((dim) => (
                <div key={dim} className="dimension-cell">
                  <span className="muted">{dim.replace('_', ' ')}</span>
                  <strong>{evaluation[dim] !== null ? evaluation[dim]!.toFixed(2) : '--'}</strong>
                </div>
              ))}
              {evaluation.flagged && <Badge tone="danger">Flagged for review</Badge>}
            </div>
          )}
          {evaluation && evaluation.status === 'skipped' && (
            <p className="muted">Evaluation skipped: {evaluation.error_message}</p>
          )}
          {evaluation && evaluation.status === 'failed' && (
            <ErrorBanner message={`Evaluation failed: ${evaluation.error_message}`} />
          )}
        </div>
      )}
    </div>
  )
}
