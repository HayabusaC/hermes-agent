// windows-nsis.ts — the Windows NSIS installer's updater owner.
//
// MSIX installs are updated by the OS App Installer (see app-installer.ts);
// a NSIS install has no such owner, so electron-updater drives it: it fetches
// `latest.yml` from the generic feed baked into `resources/app-update.yml`,
// downloads the installer, and runs it after this process exits.
//
// The mechanism name stays 'electron-updater' (the same stamp value macOS uses)
// so the install stamp vocabulary keeps one meaning: "the bundled
// electron-updater client owns the swap". Platform dispatch happens in main.ts,
// because the macOS side needs MacUpdater and the version sequencing that goes
// with it, while Windows needs NsisUpdater over a plain generic feed.

import electronUpdater from 'electron-updater'

import type { UpdaterApplyResultWire, UpdaterStatusWire, UpdaterStrategy } from './index'

export interface WindowsNsisDeps {
  appVersion: string
  /** Release channel baked into the install stamp ('stable' / 'canary'). */
  channel: string
  /** The light (remote-only) variant ships no backend to stop before a swap. */
  light: boolean
  /** `updates.feed_base_url` from config.yaml, or '' to use app-update.yml. */
  feedBaseUrl: string
  log: (message: string) => void
  /** Release whatever this process owns before the installer replaces it. */
  beforeInstall: () => Promise<void>
  /** Undo `beforeInstall` when the install cannot proceed. */
  onInstallFailure: () => Promise<void>
}

export class WindowsNsisStrategy implements UpdaterStrategy {
  readonly mechanism = 'electron-updater'

  private readonly updater: electronUpdater.NsisUpdater
  private busy = false

  constructor(private readonly deps: WindowsNsisDeps) {
    // The feed URL is optional: electron-builder always writes
    // resources/app-update.yml when a `publish` block exists, and letting the
    // updater read it keeps the baked config authoritative. An explicit
    // feedBaseUrl (config.yaml override) wins so a self-hosted feed can move
    // without rebuilding.
    const url = deps.feedBaseUrl.trim()
    this.updater = url
      ? new electronUpdater.NsisUpdater({ provider: 'generic', url })
      : new electronUpdater.NsisUpdater()

    this.updater.autoDownload = false
    this.updater.autoInstallOnAppQuit = false
    this.updater.autoRunAppAfterInstall = true
    this.updater.allowDowngrade = false
    // Every build of the same upstream release is a prerelease of it
    // (0.22.5-17), so the updater must consider prerelease versions at all.
    this.updater.allowPrerelease = true
    // electron-updater derives the feed FILE NAME from the channel:
    // channel 'stable' makes it request `stable.yml`, and this fork only ever
    // publishes `latest.yml` (electron-builder writes that name for a plain
    // release, not a channel build). Pin the channel so the requested file and
    // the published file cannot drift apart.
    this.updater.channel = 'latest'
    this.updater.logger = {
      info: (message?: unknown) => deps.log(`windows updater: ${String(message ?? '')}`),
      warn: (message?: unknown) => deps.log(`windows updater: ${String(message ?? '')}`),
      error: (message?: unknown) => deps.log(`windows updater: ${String(message ?? '')}`),
      debug: () => undefined
    } as unknown as electronUpdater.NsisUpdater['logger']
    this.updater.on('error', error => deps.log(`windows updater: ${error.message}`))
    this.updater.on('download-progress', progress => {
      deps.log(`windows updater: ${progress.percent.toFixed(0)}% of ${progress.total} bytes`)
    })
  }

  async check(): Promise<UpdaterStatusWire> {
    const base: UpdaterStatusWire = {
      supported: true,
      mechanism: this.mechanism,
      channel: this.deps.channel,
      currentVersion: this.deps.appVersion,
      fetchedAt: Date.now()
    }
    try {
      const result = await this.updater.checkForUpdates()
      const latest = result?.updateInfo?.version ?? null
      const newer = latest !== null && this.isNewer(latest)
      return {
        ...base,
        latestTag: latest,
        updateAvailable: newer,
        ...(newer ? {} : { message: 'You are on the latest version.' })
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error)
      this.deps.log(`windows updater: check failed: ${message}`)
      return { ...base, error: message, updateAvailable: false }
    }
  }

  async apply(): Promise<UpdaterApplyResultWire> {
    if (this.busy) {
      throw new Error('An update operation is already in progress.')
    }
    this.busy = true
    let stopped = false
    try {
      const result = await this.updater.checkForUpdates()
      const latest = result?.updateInfo?.version ?? null
      if (!latest || !this.isNewer(latest)) {
        return { ok: true, mechanism: this.mechanism, message: 'You are on the latest version.' }
      }

      this.deps.log(`windows updater: downloading ${latest}`)
      await this.updater.downloadUpdate()

      // Hand the machine over before the installer runs: nothing of this
      // process may still hold the install directory when it is replaced.
      await this.deps.beforeInstall()
      stopped = true

      // quitAndInstall must run outside this turn's promise chain, or the
      // installer waits on the process it is about to replace.
      setImmediate(() => {
        try {
          this.updater.quitAndInstall(false, true)
        } catch (error) {
          this.deps.log(`windows updater: quitAndInstall failed: ${String(error)}`)
        }
      })
      return { ok: true, mechanism: this.mechanism, message: `Installing ${latest}.` }
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error)
      this.deps.log(`windows updater: apply failed: ${message}`)
      if (stopped) {
        await this.deps.onInstallFailure()
      }
      return { ok: false, mechanism: this.mechanism, error: message }
    } finally {
      this.busy = false
    }
  }

  private isNewer(latest: string): boolean {
    return isNewerVersion(latest, this.deps.appVersion)
  }
}

/** Semver ordering, dependency-free.
 *
 *  Split out because the installer version is `<upstream>-<run>`: a prerelease
 *  tail (`0.22.5-17` vs `0.22.5-9`) must order numerically — a plain numeric
 *  compare of the core would call those two equal and the update would never
 *  surface. Rules implemented: compare core numerically; a release outranks its
 *  prereleases; prerelease identifiers compare numerically when both are
 *  numbers, lexically otherwise; build metadata is ignored.
 */
export function isNewerVersion(latest: string, current: string): boolean {
  return compareVersions(latest, current) > 0
}

export function compareVersions(a: string, b: string): number {
  const left = splitVersion(a)
  const right = splitVersion(b)
  const coreLength = Math.max(left.core.length, right.core.length)

  for (let i = 0; i < coreLength; i += 1) {
    const x = left.core[i] ?? 0
    const y = right.core[i] ?? 0

    if (x !== y) {
      return x > y ? 1 : -1
    }
  }

  // A release outranks any prerelease of the same core.
  if (left.pre.length === 0 && right.pre.length === 0) {
    return 0
  }

  if (left.pre.length === 0) {
    return 1
  }

  if (right.pre.length === 0) {
    return -1
  }

  const preLength = Math.max(left.pre.length, right.pre.length)

  for (let i = 0; i < preLength; i += 1) {
    const x = left.pre[i]
    const y = right.pre[i]

    if (x === undefined) {
      return -1
    }

    if (y === undefined) {
      return 1
    }

    if (x === y) {
      continue
    }

    if (typeof x === 'number' && typeof y === 'number') {
      return x > y ? 1 : -1
    }

    // Numeric identifiers sort before alphanumeric ones (semver §11).
    if (typeof x === 'number') {
      return -1
    }

    if (typeof y === 'number') {
      return 1
    }

    return String(x) > String(y) ? 1 : -1
  }

  return 0
}

function splitVersion(value: string): { core: number[]; pre: (number | string)[] } {
  const clean = value
    .trim()
    .replace(/^v/i, '')
    .split('+')[0]
  const dash = clean.indexOf('-')
  const corePart = dash === -1 ? clean : clean.slice(0, dash)
  const prePart = dash === -1 ? '' : clean.slice(dash + 1)
  const core = corePart.split('.').map(piece => {
    const parsed = Number.parseInt(piece, 10)

    return Number.isFinite(parsed) ? parsed : 0
  })
  const pre = prePart
    ? prePart.split('.').map(piece => {
        const parsed = Number.parseInt(piece, 10)

        return Number.isFinite(parsed) && String(parsed) === piece ? parsed : piece
      })
    : []

  return { core, pre }
}
