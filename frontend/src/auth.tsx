/* eslint-disable react-refresh/only-export-components -- context module intentionally exports the provider, hook and role helpers */
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { api, clearTokens, getToken, setTokens } from './api/client'
import type { User } from './types'

interface AuthState {
  user: User | null
  loading: boolean
  error: string | null
  login: (email: string, password: string) => Promise<void>
  register: (email: string, fullName: string, password: string, role: string) => Promise<void>
  logout: () => void
  refresh: () => Promise<void>
}

const AuthContext = createContext<AuthState | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [loading, setLoading] = useState<boolean>(Boolean(getToken()))
  const [error, setError] = useState<string | null>(null)

  const loadMe = useCallback(async () => {
    if (!getToken()) {
      setUser(null)
      setLoading(false)
      return
    }
    try {
      const me = await api.get<User>('/api/auth/me')
      setUser(me)
      setError(null)
    } catch {
      clearTokens()
      setUser(null)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void loadMe()
  }, [loadMe])

  const login = useCallback(async (email: string, password: string) => {
    setError(null)
    const tokens = await api.post<{ access_token: string; refresh_token: string }>('/api/auth/login', {
      email,
      password,
    })
    setTokens(tokens.access_token, tokens.refresh_token)
    await loadMe()
  }, [loadMe])

  const register = useCallback(
    async (email: string, fullName: string, password: string, role: string) => {
      setError(null)
      const tokens = await api.post<{ access_token: string; refresh_token: string }>('/api/auth/register', {
        email,
        full_name: fullName,
        password,
        role,
      })
      setTokens(tokens.access_token, tokens.refresh_token)
      await loadMe()
    },
    [loadMe],
  )

  const logout = useCallback(() => {
    clearTokens()
    setUser(null)
  }, [])

  const value = useMemo(
    () => ({ user, loading, error, login, register, logout, refresh: loadMe }),
    [user, loading, error, login, register, logout, loadMe],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used inside AuthProvider')
  return ctx
}

export const can = {
  admin: (u: User | null) => u?.role === 'admin',
  manageRubric: (u: User | null) => u?.role === 'admin' || u?.role === 'senior_reviewer',
  adjudicate: (u: User | null) => u?.role === 'admin' || u?.role === 'adjudicator' || u?.role === 'senior_reviewer',
}
