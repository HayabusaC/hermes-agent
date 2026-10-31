/**
 * The "Google Antigravity" card in Settings → Providers.
 *
 * A fork-local surface: the provider is a plugin on the gateway, so it is not
 * in `/api/providers/oauth`. The card renders nothing when the plugin is not
 * installed or not enabled (status returns null), which keeps this component
 * safe on a stock gateway.
 *
 * Sign-in runs in the app shell's loopback listener (see lib/antigravity-login),
 * so it works against a remote gateway — the browser's redirect comes back to
 * this machine, not the backend's.
 */

import { useCallback, useEffect, useState } from 'react'

import type { ProfileScope } from '@/api/client'
import { Button } from '@/components/ui/button'
import {
  type AntigravityStatus,
  canSignInAntigravity,
  getAntigravityStatus,
  signInAntigravity,
  signOutAntigravity
} from '@/lib/antigravity-login'
import { notify, notifyError } from '@/store/notifications'

const LABEL = 'Google Antigravity'
const HINT = 'Antigravity / Cloud Code Assist · Google sign-in, quota-backed'

export function AntigravityProviderRow({ profile }: { profile?: ProfileScope }) {
  const [status, setStatus] = useState<AntigravityStatus | null | undefined>(undefined)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<null | string>(null)

  const refresh = useCallback(() => {
    void getAntigravityStatus(profile).then(setStatus)
  }, [profile])

  useEffect(refresh, [refresh])

  // undefined = still loading, null = plugin absent → no row at all.
  if (status === undefined || status === null) {
    return null
  }

  const connectable = canSignInAntigravity()

  async function signIn() {
    setBusy(true)
    setError(null)

    try {
      const result = await signInAntigravity(profile)

      if (result.warning) {
        notify({ kind: 'warning', message: result.warning })
      } else {
        notify({ message: `Signed in to ${LABEL}` })
      }

      refresh()
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err)
      setError(message)
      notifyError(err, `${LABEL} sign-in failed`)
    } finally {
      setBusy(false)
    }
  }

  async function signOut() {
    setBusy(true)
    setError(null)

    try {
      await signOutAntigravity(profile)
      refresh()
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err)
      setError(message)
    } finally {
      setBusy(false)
    }
  }

  const detail = status.signed_in
    ? [status.email, status.project].filter(Boolean).join(' · ') || 'signed in'
    : connectable
      ? 'Not signed in'
      : 'Sign in from the terminal: hermes auth add antigravity'

  return (
    <div className="flex items-center justify-between gap-3 rounded-xl border border-(--ui-border) px-3 py-2">
      <div className="min-w-0">
        <div className="flex items-center gap-2 text-[length:var(--conversation-body-font-size)]">
          <span className="truncate font-medium">{LABEL}</span>
        </div>
        <p className="truncate text-[length:var(--conversation-caption-font-size)] text-(--ui-text-tertiary)">{HINT}</p>
        <p className="truncate text-[length:var(--conversation-caption-font-size)] text-(--ui-text-secondary)">{detail}</p>
        {error && (
          <p className="truncate text-[length:var(--conversation-caption-font-size)] text-(--ui-text-danger)">{error}</p>
        )}
      </div>
      {status.signed_in ? (
        <Button disabled={busy} onClick={() => void signOut()} size="inline" type="button" variant="text">
          Disconnect
        </Button>
      ) : (
        <Button disabled={busy || !connectable} onClick={() => void signIn()} size="inline" type="button" variant="textStrong">
          {busy ? 'Signing in…' : 'Sign in'}
        </Button>
      )}
    </div>
  )
}
