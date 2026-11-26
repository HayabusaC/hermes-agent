/**
 * Hermes Light (`HERMES_DESKTOP_VARIANT=light`) is the remote-only client: the
 * artifact ships no agent runtime, so every path that resolves, spawns,
 * installs, repairs or updates a LOCAL agent must be unavailable. This module
 * owns that one decision, so the main process, the first-run gate and their
 * tests cannot drift apart.
 */

/** Backend-resolve sentinel: this artifact has nothing local to spawn. */
export const LIGHT_REMOTE_ONLY_KIND = 'light-remote-only'

/** The reason string shared by logs and the boot failure surface. */
export const LIGHT_REMOTE_ONLY_REASON =
  'Hermes Light has no local agent runtime. Connect a remote Hermes backend instead.'

export function isLightPayload(payload: unknown): boolean {
  return payload === 'light'
}

export function isRemoteOnlyBackendKind(kind: unknown): boolean {
  return kind === LIGHT_REMOTE_ONLY_KIND
}

/**
 * Kinds whose boot parks until the renderer answers the first-run gate:
 * `bootstrap-needed` (a local install could be driven) and the remote-only
 * sentinel (only a remote answer exists).
 */
export function isFirstRunGateKind(kind: unknown): boolean {
  return kind === 'bootstrap-needed' || kind === LIGHT_REMOTE_ONLY_KIND
}

/** Shared refusal for every local-runtime IPC on a light artifact. */
export interface LocalRuntimeRefusal {
  ok: false
  error: 'light-remote-only'
  remoteOnly: true
}

export function refuseLocalRuntime(): LocalRuntimeRefusal {
  return { ok: false, error: 'light-remote-only', remoteOnly: true }
}
