/**
 * antigravity-login.ts
 *
 * Sign-in for the local `antigravity` model provider (Google Antigravity /
 * Cloud Code Assist). The provider is a *plugin* on the gateway, so its OAuth
 * does not ride `/api/providers/oauth` (that catalog only speaks
 * `device_code` and `external`). It has its own small API instead:
 *
 *   GET  /api/plugins/antigravity-login/status
 *   POST /api/plugins/antigravity-login/start     { client_redirect_uri }
 *   POST /api/plugins/antigravity-login/complete  { callback_url }
 *   POST /api/plugins/antigravity-login/logout
 *
 * The interesting half is the callback: Google's Antigravity client only
 * allows loopback redirects, and this app usually talks to a REMOTE gateway, so
 * the browser's `http://127.0.0.1:<port>` lands on THIS machine, not the
 * backend's. `window.hermesDesktop.mcpOauth` is the existing primitive for
 * exactly that (it is what MCP OAuth uses against a remote backend): bind a
 * one-shot ephemeral loopback listener here, hand its URI to the gateway as
 * `client_redirect_uri`, and relay the captured `code`/`state` back.
 *
 * The PKCE verifier never leaves the gateway; this module only ever sees the
 * authorization code.
 */

import { capabilityScoped, hermesApi, type ProfileScope } from '@/api/client'

const API = '/api/plugins/antigravity-login'
// Google's loopback exchange is quick; the human part is the browser sign-in.
const LOGIN_TIMEOUT_MS = 5 * 60 * 1000

export interface AntigravityStatus {
  signed_in: boolean
  provider: string
  email?: string
  project?: string
  endpoint?: string
  expires_in?: number
}

export interface AntigravityLoginResult {
  ok: boolean
  email: string
  project: string
  warning?: string
}

function bridge() {
  return typeof window !== 'undefined' ? window.hermesDesktop?.mcpOauth : undefined
}

/** Whether this app shell can catch a loopback redirect (packaged desktop does; web dashboard cannot). */
export function canSignInAntigravity(): boolean {
  return Boolean(bridge())
}

export async function getAntigravityStatus(profile?: ProfileScope): Promise<AntigravityStatus | null> {
  try {
    return await hermesApi<AntigravityStatus>({ ...capabilityScoped(profile), path: `${API}/status` })
  } catch {
    // Plugin not installed / not enabled on this gateway: no row, no error.
    return null
  }
}

export async function signInAntigravity(profile?: ProfileScope): Promise<AntigravityLoginResult> {
  const oauth = bridge()

  if (!oauth) {
    throw new Error('This build cannot catch the sign-in redirect; run `hermes auth add antigravity` instead.')
  }

  const listener = await oauth.listen()

  try {
    const started = await hermesApi<{ auth_url: string; state: string; redirect_uri: string }>({
      ...capabilityScoped(profile),
      path: `${API}/start`,
      method: 'POST',
      body: { client_redirect_uri: listener.redirectUri }
    })

    await window.hermesDesktop.openExternal(started.auth_url)
    const callback = await oauth.wait(listener.id, LOGIN_TIMEOUT_MS)

    if (callback.error) {
      throw new Error(`Google declined the sign-in: ${callback.error}`)
    }

    if (!callback.code) {
      throw new Error('Google did not return an authorization code.')
    }

    const callbackUrl = `${listener.redirectUri}?code=${encodeURIComponent(callback.code)}&state=${encodeURIComponent(
      callback.state ?? started.state
    )}`

    return await hermesApi<AntigravityLoginResult>({
      ...capabilityScoped(profile),
      path: `${API}/complete`,
      method: 'POST',
      body: { callback_url: callbackUrl },
      timeoutMs: 60_000
    })
  } finally {
    await oauth.cancel(listener.id).catch(() => false)
  }
}

export async function signOutAntigravity(profile?: ProfileScope): Promise<boolean> {
  const result = await hermesApi<{ ok: boolean; cleared: boolean }>({
    ...capabilityScoped(profile),
    path: `${API}/logout`,
    method: 'POST'
  })

  return Boolean(result.cleared)
}
