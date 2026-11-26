/**
 * What This device means on this artifact, resolved without starting anything.
 * A missing bridge fails closed: neither a click nor the gateway keeper may
 * reach runBootstrap unseen.
 */
export interface LocalBackendProbe {
  /** true = an installer would have to run before This device can serve. */
  bootstrapNeeded: boolean
  /** true = Hermes Light: there is no local runtime and no installer at all. */
  remoteOnly: boolean
}

export async function probeLocalBackend(): Promise<LocalBackendProbe> {
  const probe = window.hermesDesktop?.probeLocalBackend

  if (!probe) {
    return { bootstrapNeeded: true, remoteOnly: false }
  }

  const result = await probe()

  return {
    bootstrapNeeded: result.bootstrapNeeded === true,
    remoteOnly: result.remoteOnly === true
  }
}

/** Whether This device would need the installer. */
export async function localBootstrapNeeded(): Promise<boolean> {
  return (await probeLocalBackend()).bootstrapNeeded
}
