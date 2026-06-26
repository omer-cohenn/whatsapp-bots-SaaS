// Tenant-wide unread-message count for the WhatsApp-style badge on the "שיחות"
// nav tab (decision 0021, goal 12).
//
// The number comes from `unread_total` on GET /api/conversations. We poll it on
// a light interval so the badge stays fresh while the owner works on other tabs,
// and expose `refresh()` so the conversations page can update it immediately
// after fetching its list or opening a chat (opening resets that conversation's
// unread to 0 server-side). Kept deliberately small — a single number + a
// refresh, no global store. Only mounted for authenticated owners.

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from 'react'
import { useAuth } from '../auth/AuthContext'
import { getConversations } from '../lib/dashboardClient'

type UnreadState = {
  /** Sum of unread customer messages across the tenant's conversations. */
  unreadTotal: number
  /** Re-fetch the count now (e.g. after opening/closing a conversation). */
  refresh: () => void
}

const UnreadContext = createContext<UnreadState | null>(null)

// How often to re-poll the unread total while the app is open (ms).
const POLL_INTERVAL_MS = 30_000

export function UnreadProvider({ children }: { children: ReactNode }) {
  const { authed } = useAuth()
  const [unreadTotal, setUnreadTotal] = useState(0)
  // Guards against setting state after unmount.
  const mountedRef = useRef(true)

  const refresh = useCallback(() => {
    // Only authenticated owners have a tenant to count for; visitors stay at 0.
    if (!authed) return
    getConversations()
      .then((res) => {
        if (mountedRef.current) setUnreadTotal(res.unread_total ?? 0)
      })
      .catch(() => {
        // A failed poll must never break the UI — keep the last known count.
      })
  }, [authed])

  useEffect(() => {
    mountedRef.current = true
    // Reset when logging out so a stale count never lingers.
    if (!authed) {
      setUnreadTotal(0)
      return () => {
        mountedRef.current = false
      }
    }
    refresh()
    const id = window.setInterval(refresh, POLL_INTERVAL_MS)
    return () => {
      mountedRef.current = false
      window.clearInterval(id)
    }
  }, [authed, refresh])

  return (
    <UnreadContext.Provider value={{ unreadTotal, refresh }}>
      {children}
    </UnreadContext.Provider>
  )
}

/**
 * Read the unread state. Safe to call outside the provider (the conversations
 * page may render before the provider in some trees): returns a no-op default
 * so the badge simply stays hidden.
 */
export function useUnread(): UnreadState {
  return useContext(UnreadContext) ?? { unreadTotal: 0, refresh: () => {} }
}
