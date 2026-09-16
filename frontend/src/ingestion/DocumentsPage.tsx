import { useRef, useState, type ChangeEvent } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { listDocuments, uploadDocument } from '../api/documents'
import { getDomain } from '../api/domains'
import { ApiError } from '../api/client'
import { useToast } from '../components/ToastProvider'
import type { DocumentStatus } from '../api/types'
import { Badge } from '../components/Badge'
import { Button } from '../components/Button'
import { EmptyState } from '../components/EmptyState'
import { ErrorBanner } from '../components/ErrorBanner'
import { SkeletonTable } from '../components/Skeleton'

const NON_TERMINAL: DocumentStatus[] = ['pending', 'processing', 'indexing']

const STATUS_TONE: Record<DocumentStatus, 'neutral' | 'success' | 'warning' | 'danger' | 'info'> = {
  pending: 'neutral',
  processing: 'info',
  indexing: 'info',
  ready: 'success',
  failed: 'danger',
}

export function DocumentsPage() {
  const { domainId } = useParams<{ domainId: string }>()
  const queryClient = useQueryClient()
  const { addToast } = useToast()
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [uploadError, setUploadError] = useState<string | null>(null)

  const domainQuery = useQuery({
    queryKey: ['domain', domainId],
    queryFn: () => getDomain(domainId!),
    enabled: Boolean(domainId),
  })

  const documentsQuery = useQuery({
    queryKey: ['documents', domainId],
    queryFn: () => listDocuments(domainId!),
    enabled: Boolean(domainId),
    // Keep polling only while something is still in flight -- avoids
    // hammering the API once every document has reached a terminal state.
    refetchInterval: (query) => {
      const documents = query.state.data
      return documents?.some((d) => NON_TERMINAL.includes(d.status)) ? 2000 : false
    },
  })

  const uploadMutation = useMutation({
    mutationFn: (file: File) => uploadDocument(domainId!, file),
    onSuccess: (doc) => {
      queryClient.invalidateQueries({ queryKey: ['documents', domainId] })
      if (fileInputRef.current) fileInputRef.current.value = ''
      addToast(`"${doc.filename}" uploaded -- processing`, 'success')
    },
    onError: (err) => setUploadError(err instanceof ApiError ? err.message : 'Could not upload document'),
  })

  function handleFileChange(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0]
    if (!file) return
    setUploadError(null)
    uploadMutation.mutate(file)
  }

  const uploadButton = (
    <div>
      <input
        ref={fileInputRef}
        type="file"
        onChange={handleFileChange}
        style={{ display: 'none' }}
        accept=".pdf,.docx"
      />
      <Button onClick={() => fileInputRef.current?.click()} disabled={uploadMutation.isPending}>
        {uploadMutation.isPending ? 'Uploading...' : 'Upload document'}
      </Button>
    </div>
  )

  return (
    <div>
      <p>
        <Link to={`/domains/${domainId}`}>&larr; Back to {domainQuery.data?.name ?? 'domain'}</Link>
      </p>
      <div className="page-header">
        <h1>Documents</h1>
        {uploadButton}
      </div>
      {uploadError && <ErrorBanner message={uploadError} />}
      {documentsQuery.error && (
        <ErrorBanner
          message={documentsQuery.error instanceof ApiError ? documentsQuery.error.message : 'Could not load documents'}
        />
      )}
      {documentsQuery.isLoading && <SkeletonTable />}
      {documentsQuery.data?.length === 0 && (
        <EmptyState
          title="No documents yet"
          description="Upload a PDF or DOCX to start building this domain's knowledge base."
          action={{ label: 'Upload document', onClick: () => fileInputRef.current?.click() }}
        />
      )}
      {documentsQuery.data && documentsQuery.data.length > 0 && (
        <table className="table">
          <thead>
            <tr>
              <th>Filename</th>
              <th>Status</th>
              <th>OCR</th>
              <th>Uploaded</th>
            </tr>
          </thead>
          <tbody>
            {documentsQuery.data.map((doc) => (
              <tr key={doc.id}>
                <td>
                  <Link to={`/domains/${domainId}/documents/${doc.id}/chunks`}>{doc.filename}</Link>
                </td>
                <td>
                  <Badge tone={STATUS_TONE[doc.status]}>{doc.status}</Badge>
                  {doc.status === 'failed' && doc.error_message && <div className="muted">{doc.error_message}</div>}
                </td>
                <td>{doc.ocr_used ? 'Yes' : 'No'}</td>
                <td>{new Date(doc.uploaded_at).toLocaleString()}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}
