import { useState } from 'react'
import { useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  createGoldenQaItem,
  deleteGoldenQaItem,
  listGoldenQaItems,
  triggerGoldenRegression,
  updateGoldenQaItem,
} from '../api/evaluation'
import { ApiError } from '../api/client'
import { useToast } from '../components/ToastProvider'
import type { GoldenQAItemResponse } from '../api/types'
import { Button } from '../components/Button'
import { EmptyState } from '../components/EmptyState'
import { ErrorBanner } from '../components/ErrorBanner'
import { Modal } from '../components/Modal'
import { Skeleton } from '../components/Skeleton'

export function GoldenQAPage() {
  const { domainId } = useParams<{ domainId: string }>()
  const queryClient = useQueryClient()
  const { addToast } = useToast()
  const [editingItem, setEditingItem] = useState<GoldenQAItemResponse | 'new' | null>(null)
  const [regressionError, setRegressionError] = useState<string | null>(null)

  const itemsQuery = useQuery({
    queryKey: ['golden-qa', domainId],
    queryFn: () => listGoldenQaItems(domainId!),
    enabled: Boolean(domainId),
  })

  const deleteMutation = useMutation({
    mutationFn: (itemId: string) => deleteGoldenQaItem(domainId!, itemId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['golden-qa', domainId] })
      addToast('Golden item deleted', 'success')
    },
  })

  const regressionMutation = useMutation({
    mutationFn: () => triggerGoldenRegression(domainId!),
    onSuccess: () => addToast('Regression run queued -- results will appear in the quality dashboard shortly.', 'success'),
    onError: (err) => setRegressionError(err instanceof ApiError ? err.message : 'Could not trigger regression'),
  })

  if (itemsQuery.isLoading) {
    return (
      <div>
        <h1>Golden Q&amp;A</h1>
        <Skeleton height="8rem" />
      </div>
    )
  }

  return (
    <div>
      <div className="page-header">
        <h1>Golden Q&amp;A</h1>
        <div>
          <Button variant="ghost" onClick={() => regressionMutation.mutate()} disabled={regressionMutation.isPending}>
            {regressionMutation.isPending ? 'Queuing...' : 'Run regression now'}
          </Button>{' '}
          <Button onClick={() => setEditingItem('new')}>Add item</Button>
        </div>
      </div>
      {regressionError && <ErrorBanner message={regressionError} />}
      {itemsQuery.error && (
        <ErrorBanner
          message={itemsQuery.error instanceof ApiError ? itemsQuery.error.message : 'Could not load golden Q&A items'}
        />
      )}

      <div className="golden-qa-list">
        {itemsQuery.data?.map((item) => (
          <div key={item.id} className="golden-qa-card">
            <p>
              <strong>Q:</strong> {item.question}
            </p>
            <p>
              <strong>Expected:</strong> {item.expected_answer}
            </p>
            {item.expected_citations.length > 0 && (
              <p className="muted">Citations: {item.expected_citations.join(', ')}</p>
            )}
            <div className="moderation-actions">
              <Button variant="ghost" onClick={() => setEditingItem(item)}>
                Edit
              </Button>
              <Button variant="danger" onClick={() => deleteMutation.mutate(item.id)} disabled={deleteMutation.isPending}>
                Delete
              </Button>
            </div>
          </div>
        ))}
      </div>
      {itemsQuery.data?.length === 0 && (
        <EmptyState
          title="No golden Q&A items yet"
          description="Curate known-good question/answer pairs to catch regressions automatically after ingestion or model changes."
          action={{ label: 'Add item', onClick: () => setEditingItem('new') }}
        />
      )}

      {editingItem && (
        <GoldenQaFormModal
          domainId={domainId!}
          item={editingItem === 'new' ? null : editingItem}
          onClose={() => setEditingItem(null)}
          onSuccess={(isNew) => {
            setEditingItem(null)
            queryClient.invalidateQueries({ queryKey: ['golden-qa', domainId] })
            addToast(isNew ? 'Golden item added' : 'Golden item updated', 'success')
          }}
        />
      )}
    </div>
  )
}

function GoldenQaFormModal({
  domainId,
  item,
  onClose,
  onSuccess,
}: {
  domainId: string
  item: GoldenQAItemResponse | null
  onClose: () => void
  onSuccess: (isNew: boolean) => void
}) {
  const [question, setQuestion] = useState(item?.question ?? '')
  const [expectedAnswer, setExpectedAnswer] = useState(item?.expected_answer ?? '')
  const [citations, setCitations] = useState(item?.expected_citations.join(', ') ?? '')
  const [error, setError] = useState<string | null>(null)

  const mutation = useMutation({
    mutationFn: () => {
      const payload = {
        question,
        expected_answer: expectedAnswer,
        expected_citations: citations
          .split(',')
          .map((c) => c.trim())
          .filter(Boolean),
      }
      return item ? updateGoldenQaItem(domainId, item.id, payload) : createGoldenQaItem(domainId, payload)
    },
    onSuccess: () => onSuccess(!item),
    onError: (err) => setError(err instanceof ApiError ? err.message : 'Could not save item'),
  })

  return (
    <Modal title={item ? 'Edit golden item' : 'Add golden item'} onClose={onClose}>
      {error && <ErrorBanner message={error} />}
      <form
        onSubmit={(e) => {
          e.preventDefault()
          setError(null)
          mutation.mutate()
        }}
      >
        <label>
          Question
          <textarea value={question} onChange={(e) => setQuestion(e.target.value)} rows={2} required />
        </label>
        <label>
          Expected answer
          <textarea value={expectedAnswer} onChange={(e) => setExpectedAnswer(e.target.value)} rows={3} required />
        </label>
        <label>
          Expected citations (comma-separated)
          <input value={citations} onChange={(e) => setCitations(e.target.value)} />
        </label>
        <Button type="submit" disabled={mutation.isPending}>
          {mutation.isPending ? 'Saving...' : 'Save'}
        </Button>
      </form>
    </Modal>
  )
}
