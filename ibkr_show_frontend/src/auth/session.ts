import { reactive, readonly } from 'vue'

import { fetchAuthSession, login, logout } from '@/api/auth'

const AUTH_SESSION_CACHE_KEY = 'ibkr-show.auth-session'
const AUTH_SESSION_CACHE_TTL_MS = 30_000

type AuthState = {
  initialized: boolean
  loading: boolean
  authenticated: boolean
  username: string | null
}

const authState = reactive<AuthState>({
  initialized: false,
  loading: false,
  authenticated: false,
  username: null,
})

let pendingSessionRequest: Promise<void> | null = null

function readCachedAuthState():
  | {
      authenticated: boolean
      username: string | null
      cachedAt: number
    }
  | null {
  if (typeof window === 'undefined') {
    return null
  }

  const raw = window.sessionStorage.getItem(AUTH_SESSION_CACHE_KEY)
  if (!raw) {
    return null
  }

  try {
    const parsed = JSON.parse(raw) as {
      authenticated: boolean
      username: string | null
      cachedAt: number
    }
    if (Date.now() - parsed.cachedAt > AUTH_SESSION_CACHE_TTL_MS) {
      window.sessionStorage.removeItem(AUTH_SESSION_CACHE_KEY)
      return null
    }
    return parsed
  } catch {
    window.sessionStorage.removeItem(AUTH_SESSION_CACHE_KEY)
    return null
  }
}

function writeCachedAuthState(authenticated: boolean, username: string | null): void {
  if (typeof window === 'undefined') {
    return
  }

  window.sessionStorage.setItem(
    AUTH_SESSION_CACHE_KEY,
    JSON.stringify({
      authenticated,
      username,
      cachedAt: Date.now(),
    }),
  )
}

function applyAuthState(authenticated: boolean, username: string | null): void {
  authState.authenticated = authenticated
  authState.username = authenticated ? username : null
  authState.initialized = true
  writeCachedAuthState(authState.authenticated, authState.username)
}

export async function ensureAuthSession(force = false): Promise<void> {
  if (!force && !authState.initialized) {
    const cachedState = readCachedAuthState()
    if (cachedState) {
      applyAuthState(cachedState.authenticated, cachedState.username)
      return
    }
  }
  if (authState.initialized && !force) {
    return
  }
  if (pendingSessionRequest && !force) {
    return pendingSessionRequest
  }

  pendingSessionRequest = (async () => {
    authState.loading = true
    try {
      const session = await fetchAuthSession()
      applyAuthState(session.authenticated, session.username)
    } catch {
      applyAuthState(false, null)
    } finally {
      authState.loading = false
      pendingSessionRequest = null
    }
  })()

  return pendingSessionRequest
}

export async function loginWithCredentials(username: string, password: string): Promise<void> {
  authState.loading = true
  try {
    const session = await login({ username, password })
    applyAuthState(session.authenticated, session.username)
  } finally {
    authState.loading = false
  }
}

export async function logoutCurrentSession(): Promise<void> {
  authState.loading = true
  try {
    await logout()
    applyAuthState(false, null)
  } finally {
    authState.loading = false
  }
}

export function useAuthSession() {
  return {
    authState: readonly(authState),
    ensureAuthSession,
    loginWithCredentials,
    logoutCurrentSession,
  }
}
