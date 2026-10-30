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
import { gt, valid } from 'semver'

import type { UpdaterApplyResultWire, UpdaterStrategy, UpdaterStatusWire } from './index'

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
    if (/^(stable|canary)$/.test(deps.channel)) {
      this.updater.channel = deps.channel
    }
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
    // Functional API on purpose: the SemVer class shape varies across semver
    // majors (and `compare` is not on the type this tree installs).
    if (!valid(latest) || !valid(this.deps.appVersion)) {
      return latest !== this.deps.appVersion
    }

    return gt(latest, this.deps.appVersion)
  }
}
