import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'
import { setCsrfToken } from '../api/client'
import { supportApi } from '../api/support'
import type { AuthStatus } from '../types'

interface AuthValue { status: AuthStatus | null; loading: boolean; error: string; refresh: () => Promise<void>; logout: () => Promise<void>; login: () => void }
const AuthContext = createContext<AuthValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<AuthStatus | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const refresh = async () => {
    setLoading(true); setError('')
    try {
      const result = await supportApi.authStatus()
      setStatus(result); setCsrfToken(result.csrf_token)
    } catch (err) {
      setStatus(null); setCsrfToken(undefined)
      setError(err instanceof Error ? err.message : 'Sign-in status could not be checked.')
    } finally { setLoading(false) }
  }
  useEffect(() => { void refresh() }, [])
  const logout = async () => {
    await supportApi.logout()
    setCsrfToken(undefined); setStatus({ authenticated: false, user: null, permissions: { reviewer: false } })
  }
  const login = () => { window.location.assign('/api/bff/auth/login') }
  return <AuthContext.Provider value={{ status, loading, error, refresh, logout, login }}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const value = useContext(AuthContext)
  if (!value) throw new Error('AuthProvider is required.')
  return value
}
