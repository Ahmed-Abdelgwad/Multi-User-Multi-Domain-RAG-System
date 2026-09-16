import { apiGet, apiPut } from './client'
import type { UserDomainMembership, UserResponse } from './types'

export function getCurrentUser(): Promise<UserResponse> {
  return apiGet<UserResponse>('/users/me')
}

export function getCurrentUserDomains(): Promise<UserDomainMembership[]> {
  return apiGet<UserDomainMembership[]>('/users/me/domains')
}

export function listUsers(limit = 50, offset = 0): Promise<UserResponse[]> {
  return apiGet<UserResponse[]>(`/users/?limit=${limit}&offset=${offset}`)
}

export function setPlatformAdmin(userId: string, isPlatformAdmin: boolean): Promise<UserResponse> {
  return apiPut<UserResponse>(`/users/${userId}/platform-admin`, { is_platform_admin: isPlatformAdmin })
}
