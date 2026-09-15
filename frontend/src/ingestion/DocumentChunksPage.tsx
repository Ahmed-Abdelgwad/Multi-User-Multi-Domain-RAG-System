import { Link, useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { listChunks } from '../api/chunks'
import { getDocument } from '../api/documents'
import { ApiError } from '../api/client'
import { Badge } from '../components/Badge'
import { ErrorBanner } from '../components/ErrorBanner'
import { Spinner } from '../components/Spinner'

export function DocumentChunksPage() {
  const { domainId, documentId } = useParams<{ domainId: string; documentId: string }>()

  const documentQuery = useQuery({
    queryKey: ['document', domainId, documentId],
    queryFn: () => getDocument(domainId!, documentId!),
    enabled: Boolean(domainId && documentId),
  })

  const chunksQuery = useQuery({
    queryKey: ['chunks', domainId, documentId],
    queryFn: () => listChunks(domainId!, documentId!),
    enabled: Boolean(domainId && documentId),
  })

  if (documentQuery.isLoading || chunksQuery.isLoading) return <Spinner />

  return (
    <div>
      <p>
        <Link to={`/domains/${domainId}/documents`}>&larr; Back to documents</Link>
      </p>
      <h1>{documentQuery.data?.filename}</h1>
      {chunksQuery.error && (
        <ErrorBanner message={chunksQuery.error instanceof ApiError ? chunksQuery.error.message : 'Could not load chunks'} />
      )}
      <p className="muted">{chunksQuery.data?.length ?? 0} chunks</p>
      <div className="chunk-list">
        {chunksQuery.data?.map((chunk) => (
          <div key={chunk.id} className="chunk-card">
            <div className="chunk-card-header">
              <span>#{chunk.chunk_index}</span>
              <Badge tone={chunk.content_type === 'table' ? 'info' : 'neutral'}>{chunk.content_type}</Badge>
              {!chunk.is_active && <Badge tone="warning">superseded</Badge>}
            </div>
            <pre className="chunk-content">{chunk.content}</pre>
          </div>
        ))}
        {chunksQuery.data?.length === 0 && <p className="muted">No chunks yet -- check back once the document finishes indexing.</p>}
      </div>
    </div>
  )
}
