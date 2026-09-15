import { apiPost, apiPostForm } from './client'

export interface TokenResponse {
  access_token: string
  token_type: string
}

export interface RegisterInput {
  email: string
  first_name: string
  last_name: string
  password: string
}

// /auth/token uses OAuth2PasswordRequestForm -- "username" is the email.
export function login(email: string, password: string): Promise<TokenResponse> {
  const form = new URLSearchParams()
  form.set('username', email)
  form.set('password', password)
  return apiPostForm<TokenResponse>('/auth/token', form)
}

export function register(input: RegisterInput): Promise<void> {
  return apiPost<void>('/auth/', input)
}
