import { apiDelete, apiGet, apiPost } from './client'
import type { DomainResponse, DomainRole, UserDomainRoleResponse, UserResponse } from './types'

export interface DomainCreateInput {
  name: string
  description?: string
}

export interface AssignRoleInput {
  user_id: string
  role: DomainRole
}

export function listDomains(): Promise<DomainResponse[]> {
  return apiGet<DomainResponse[]>('/domains/')
}

export function getDomain(domainId: string): Promise<DomainResponse> {
  return apiGet<DomainResponse>(`/domains/${domainId}`)
}

export function createDomain(input: DomainCreateInput): Promise<DomainResponse> {
  return apiPost<DomainResponse>('/domains/', input)
}

export function archiveDomain(domainId: string): Promise<DomainResponse> {
  return apiPost<DomainResponse>(`/domains/${domainId}/archive`)
}

export function listDomainRoles(domainId: string): Promise<UserDomainRoleResponse[]> {
  return apiGet<UserDomainRoleResponse[]>(`/domains/${domainId}/roles`)
}

export function assignRole(domainId: string, input: AssignRoleInput): Promise<UserDomainRoleResponse> {
  return apiPost<UserDomainRoleResponse>(`/domains/${domainId}/roles`, input)
}

export function revokeRole(domainId: string, userId: string): Promise<void> {
  return apiDelete<void>(`/domains/${domainId}/roles/${userId}`)
}

export function lookupUsersToInvite(domainId: string, email: string): Promise<UserResponse[]> {
  return apiGet<UserResponse[]>(`/domains/${domainId}/roles/lookup?email=${encodeURIComponent(email)}`)
}
