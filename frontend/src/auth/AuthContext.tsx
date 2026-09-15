import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { setAuthToken, setUnauthorizedHandler } from '../api/client'
import { login as apiLogin, register as apiRegister, type RegisterInput } from '../api/auth'
import { getCurrentUser, getCurrentUserDomains } from '../api/users'
import type { UserDomainMembership, UserResponse } from '../api/types'

const TOKEN_STORAGE_KEY = 'rag_console_token'

interface AuthContextValue {
  token: string | null
  user: UserResponse | null
  domains: UserDomainMembership[]
  isLoading: boolean
  login: (email: string, password: string) => Promise<void>
  register: (input: RegisterInput) => Promise<void>
  logout: () => void
  refreshDomains: () => Promise<void>
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(() => localStorage.getItem(TOKEN_STORAGE_KEY))
  const [user, setUser] = useState<UserResponse | null>(null)
  const [domains, setDomains] = useState<UserDomainMembership[]>([])
  const [isLoading, setIsLoading] = useState<boolean>(Boolean(token))

  useEffect(() => {
    setAuthToken(token)
  }, [token])

  // Wired once: a 401 from any call (expired/invalid token) clears auth
  // state the same way an explicit logout does.
  useEffect(() => {
    setUnauthorizedHandler(() => {
      localStorage.removeItem(TOKEN_STORAGE_KEY)
      setToken(null)
      setUser(null)
      setDomains([])
    })
  }, [])

  useEffect(() => {
    let cancelled = false
    if (!token) {
      setIsLoading(false)
      return
    }
    setIsLoading(true)
    Promise.all([getCurrentUser(), getCurrentUserDomains()])
      .then(([profile, memberships]) => {
        if (cancelled) return
        setUser(profile)
        setDomains(memberships)
      })
      .catch(() => {
        if (cancelled) return
        localStorage.removeItem(TOKEN_STORAGE_KEY)
        setToken(null)
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [token])

  const value = useMemo<AuthContextValue>(
    () => ({
      token,
      user,
      domains,
      isLoading,
      async login(email: string, password: string) {
        const { access_token } = await apiLogin(email, password)
        localStorage.setItem(TOKEN_STORAGE_KEY, access_token)
        setToken(access_token)
      },
      async register(input: RegisterInput) {
        await apiRegister(input)
      },
      logout() {
        localStorage.removeItem(TOKEN_STORAGE_KEY)
        setToken(null)
        setUser(null)
        setDomains([])
      },
      async refreshDomains() {
        setDomains(await getCurrentUserDomains())
      },
    }),
    [token, user, domains, isLoading],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within an AuthProvider')
  return ctx
}
