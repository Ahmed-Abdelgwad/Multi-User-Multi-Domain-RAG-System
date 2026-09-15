import { apiGet } from './client'
import type { ChunkResponse } from './types'

export function listChunks(domainId: string, documentId: string): Promise<ChunkResponse[]> {
  return apiGet<ChunkResponse[]>(`/domains/${domainId}/documents/${documentId}/chunks/`)
}
