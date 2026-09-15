import { apiGet } from './client'
import type { UserDomainMembership, UserResponse } from './types'

export function getCurrentUser(): Promise<UserResponse> {
  return apiGet<UserResponse>('/users/me')
}

export function getCurrentUserDomains(): Promise<UserDomainMembership[]> {
  return apiGet<UserDomainMembership[]>('/users/me/domains')
}
