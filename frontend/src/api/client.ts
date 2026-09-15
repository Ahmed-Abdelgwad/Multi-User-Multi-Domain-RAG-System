// Thin fetch wrapper -- no axios. Handles: base URL, bearer-token
// injection, a 401 hook (auth context wires itself in via
// setUnauthorizedHandler), and normalizing both this backend's plain
// `{"detail": "..."}` error shape and FastAPI/Pydantic's 422
// `{"detail": [{"msg": ...}, ...]}` array shape into one ApiError.

const DEFAULT_BASE_URL = 'http://localhost:8001'

export function getApiBaseUrl(): string {
  return import.meta.env.VITE_API_BASE_URL ?? DEFAULT_BASE_URL
}

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

let authToken: string | null = null
let unauthorizedHandler: (() => void) | null = null

export function setAuthToken(token: string | null): void {
  authToken = token
}

export function setUnauthorizedHandler(handler: () => void): void {
  unauthorizedHandler = handler
}

function extractErrorMessage(body: unknown, fallback: string): string {
  if (body && typeof body === 'object' && 'detail' in body) {
    const detail = (body as { detail: unknown }).detail
    if (typeof detail === 'string') return detail
    if (Array.isArray(detail)) {
      return detail
        .map((item) =>
          item && typeof item === 'object' && 'msg' in item
            ? String((item as { msg: unknown }).msg)
            : JSON.stringify(item),
        )
        .join('; ')
    }
  }
  return fallback
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers)
  if (authToken) headers.set('Authorization', `Bearer ${authToken}`)

  const response = await fetch(`${getApiBaseUrl()}${path}`, { ...init, headers })

  if (response.status === 401) {
    unauthorizedHandler?.()
  }

  if (!response.ok) {
    let body: unknown = null
    try {
      body = await response.json()
    } catch {
      // no JSON body -- fall through to the generic message below
    }
    throw new ApiError(response.status, extractErrorMessage(body, `Request failed (${response.status})`))
  }

  if (response.status === 204) return undefined as T

  const contentType = response.headers.get('content-type') ?? ''
  if (contentType.includes('text/csv')) return (await response.blob()) as unknown as T
  if (!contentType.includes('application/json')) return undefined as T
  return (await response.json()) as T
}

export function apiGet<T>(path: string): Promise<T> {
  return request<T>(path)
}

export function apiPost<T>(path: string, body?: unknown): Promise<T> {
  return request<T>(path, {
    method: 'POST',
    headers: body !== undefined ? { 'Content-Type': 'application/json' } : undefined,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  })
}

export function apiPut<T>(path: string, body: unknown): Promise<T> {
  return request<T>(path, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
}

export function apiDelete<T>(path: string): Promise<T> {
  return request<T>(path, { method: 'DELETE' })
}

// /auth/token uses OAuth2PasswordRequestForm -- form-urlencoded, not JSON.
export function apiPostForm<T>(path: string, form: URLSearchParams): Promise<T> {
  return request<T>(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: form.toString(),
  })
}

export function apiUpload<T>(path: string, file: File): Promise<T> {
  const form = new FormData()
  form.append('file', file)
  // No Content-Type header -- the browser sets the multipart boundary itself.
  return request<T>(path, { method: 'POST', body: form })
}

export function apiDownloadBlob(path: string): Promise<Blob> {
  return request<Blob>(path)
}
