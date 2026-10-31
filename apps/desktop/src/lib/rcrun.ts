import { useQuery, type UseQueryResult } from '@tanstack/react-query'

import { capabilityScoped, hermesApi } from '@/api/client'

/**
 * Remote compute jobs (`rcrun` on the gateway host).
 *
 * The data comes from the user-level Python plugin `rcrun-panel`
 * (`~/.hermes/plugins/rcrun-panel/dashboard/plugin_api.py`), which is a thin
 * forwarder over the `rcrun` CLI: it reads the job manifests and asks the remote
 * host for the live unit state. So this hook, the CLI and the cron tick all see
 * one source of truth — nothing is mirrored into the app.
 */
const API = '/api/plugins/rcrun-panel'

export type RcrunStatus =
  | 'staged'
  | 'pending'
  | 'running'
  | 'fetched'
  | 'failed'
  | 'verify_failed'
  | 'cancelled'

export interface RcrunJob {
  id: string
  name: string
  project: string
  root?: string
  root_label?: string
  status: RcrunStatus
  exit?: number | null
  elapsed?: number | null
  files?: number | null
  bytes?: number | null
  out_bytes_live?: number | null
  last_activity_ago?: number | null
  tail?: string
  host?: string
  cpus?: number | null
  mem?: string | null
  lcg?: string | null
  submitted_at?: string
  pending_at?: string
  queue_pos?: number | null
  unit?: string
}

export interface RcrunAgg {
  running: number
  pending: number
  fetched: number
  failed: number
  total_wall: number
  max_running: number
}

export interface RcrunPayload {
  jobs: RcrunJob[]
  agg: RcrunAgg
  generated_at: number
  remote_ok: boolean
  remote_checked: boolean
  runs_roots: string[]
  ssh_target: string
}

export interface RcrunDispatchResult {
  code: number
  stdout: string
  stderr: string
}

/** Poll every 5s: a job's "last activity" is measured in seconds, and the
 *  backend caches its own ssh probe for ~2.5s. */
export function useRcrunJobs(profile?: string): UseQueryResult<RcrunPayload> {
  return useQuery({
    queryKey: ['rcrun', 'jobs', profile ?? 'default'],
    queryFn: () => hermesApi<RcrunPayload>({ ...capabilityScoped(profile), path: `${API}/jobs` }),
    refetchInterval: 5000,
    staleTime: 2000
  })
}

/** Same tick the cron driver runs: fill free slots from the queue, pull finished
 *  results back. Idempotent — safe on a button. */
export function dispatchRcrun(profile?: string): Promise<RcrunDispatchResult> {
  return hermesApi<RcrunDispatchResult>({
    ...capabilityScoped(profile),
    path: `${API}/dispatch`,
    method: 'POST'
  })
}

export const RCRUN_STATUS_LABEL: Record<string, string> = {
  staged: 'staged',
  pending: 'queued',
  running: 'running',
  fetched: 'done',
  failed: 'failed',
  verify_failed: 'verify failed',
  cancelled: 'cancelled'
}

export function fmtRcrunDuration(seconds?: number | null): string {
  if (seconds === null || seconds === undefined) return '—'
  const s = Math.max(0, Math.round(seconds))
  if (s < 60) return `${s}s`
  if (s < 3600) return `${Math.floor(s / 60)}m${String(s % 60).padStart(2, '0')}s`
  return `${Math.floor(s / 3600)}h${String(Math.floor((s % 3600) / 60)).padStart(2, '0')}m`
}

export function fmtRcrunBytes(bytes?: number | null): string {
  if (bytes === null || bytes === undefined) return '—'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KiB`
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MiB`
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GiB`
}
