import { apiGet, apiUpload } from './client'
import type { DocumentResponse } from './types'

export function listDocuments(domainId: string): Promise<DocumentResponse[]> {
  return apiGet<DocumentResponse[]>(`/domains/${domainId}/documents/`)
}

export function getDocument(domainId: string, documentId: string): Promise<DocumentResponse> {
  return apiGet<DocumentResponse>(`/domains/${domainId}/documents/${documentId}`)
}

export function uploadDocument(domainId: string, file: File): Promise<DocumentResponse> {
  return apiUpload<DocumentResponse>(`/domains/${domainId}/documents/`, file)
}
