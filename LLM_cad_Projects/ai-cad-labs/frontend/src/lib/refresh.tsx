import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from 'react'

/**
 * Manual refresh: a global Refresh button is the v1 reload contract
 * (no fs-watch in v1). A monotonic token surfaces subscribe
 * to via their load effect's deps; the header button bumps it, re-fetching all
 * surface data in place (no full-page reload, so scroll/route state survive).
 */
interface RefreshContextValue {
  refreshToken: number
  refresh: () => void
}

const RefreshContext = createContext<RefreshContextValue>({
  refreshToken: 0,
  refresh: () => {},
})

export function RefreshProvider({ children }: { children: ReactNode }) {
  const [refreshToken, setRefreshToken] = useState(0)
  const refresh = useCallback(() => setRefreshToken((n) => n + 1), [])
  const value = useMemo(() => ({ refreshToken, refresh }), [refreshToken, refresh])
  return <RefreshContext.Provider value={value}>{children}</RefreshContext.Provider>
}

export function useRefresh(): RefreshContextValue {
  return useContext(RefreshContext)
}
