// Auth state for the whole app.
//
// On mount we call GET /api/me. If it returns 200 we're logged in and hold the
// user/business/connection. A 401 means "not logged in" — we simply mark the
// user as unauthenticated (the AuthGate redirects to /login). Any other error
// is surfaced so the UI can show it.

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'
import { api, ApiError } from '../lib/apiClient'
import type { Business, Connection, Me, User } from './types'

type AuthState = {
  user: User | null
  business: Business | null
  connection: Connection | null
  /** Platform-operator flag (M12). Defaults to false until /api/me confirms it. */
  isAdmin: boolean
  loading: boolean
  authed: boolean
  error: string | null
  refresh: () => Promise<void>
  logout: () => Promise<void>
}

const AuthContext = createContext<AuthState | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<Me | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await api.get<Me>('/api/me')
      setMe(data)
    } catch (err) {
      setMe(null)
      // A 401 is the normal "not logged in" path — not an error to display.
      if (!(err instanceof ApiError && err.isUnauthorized)) {
        setError('אירעה תקלה בטעינת פרטי המשתמש. נסו שוב.')
      }
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void refresh()
  }, [refresh])

  const logout = useCallback(async () => {
    try {
      await api.post('/auth/logout')
    } catch {
      // Even if the call fails, clear local state and send the user to login.
    } finally {
      setMe(null)
      // Full navigation so all in-memory state is dropped cleanly.
      window.location.assign('/login')
    }
  }, [])

  const value = useMemo<AuthState>(
    () => ({
      user: me?.user ?? null,
      business: me?.business ?? null,
      connection: me?.connection ?? null,
      // Default false: a missing/false flag must never grant admin UI.
      isAdmin: me?.is_admin ?? false,
      loading,
      authed: me !== null,
      error,
      refresh,
      logout,
    }),
    [me, loading, error, refresh, logout],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within <AuthProvider>')
  return ctx
}
