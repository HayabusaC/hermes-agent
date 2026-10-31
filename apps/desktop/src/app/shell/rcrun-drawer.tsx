import { useQueryClient } from '@tanstack/react-query'
import { useStore } from '@nanostores/react'
import { useCallback, useEffect, useMemo, useState } from 'react'

import { Button } from '@/components/ui/button'
import { Codicon } from '@/components/ui/codicon'
import {
  dispatchRcrun,
  fmtRcrunBytes,
  fmtRcrunDuration,
  RCRUN_STATUS_LABEL,
  useRcrunJobs,
  type RcrunJob
} from '@/lib/rcrun'
import { cn } from '@/lib/utils'
import { $rcrunDrawerOpen, setRcrunDrawerOpen, toggleRcrunDrawer } from '@/store/rcrun'

/**
 * Remote-job surface (`rcrun`).
 *
 * A drawer, not a pane: it drops over whatever the user is looking at (chat,
 * a full page, a split tile), closes on Esc / outside click, and keeps its
 * scroll position out of the layout. The statusbar chip owns the trigger so the
 * count is visible without opening anything.
 *
 * Data: `useRcrunJobs` → `/api/plugins/rcrun-panel/jobs` → the `rcrun` CLI. The
 * drawer never invents state; a job's "last activity" is the remote `out/`
 * mtime, so a stalled job looks stalled.
 */

const STATUS_TONE: Record<string, string> = {
  running: 'text-(--ui-accent)',
  pending: 'text-(--ui-text-secondary)',
  fetched: 'text-(--ui-text-tertiary)',
  failed: 'text-destructive',
  verify_failed: 'text-destructive',
  cancelled: 'text-(--ui-text-quaternary)',
  staged: 'text-(--ui-text-quaternary)'
}

function statusLabel(job: RcrunJob): string {
  if (job.status === 'pending') return `#${job.queue_pos ?? '-'} queued`
  return RCRUN_STATUS_LABEL[job.status] ?? job.status
}

function scopeLabel(job: RcrunJob): string {
  return job.root_label ? `${job.root_label}/${job.project}` : job.project
}

function Stat({ label, value }: { label: string; value: string | number }): React.JSX.Element {
  return (
    <div className="flex min-w-[3.25rem] flex-col gap-0.5">
      <span className="text-[0.625rem] tracking-wide text-(--ui-text-quaternary) uppercase">{label}</span>
      <span className="text-[0.8125rem] font-medium tabular-nums text-foreground">{value}</span>
    </div>
  )
}

function JobRow({ job }: { job: RcrunJob }): React.JSX.Element {
  const running = job.status === 'running'
  const live = job.out_bytes_live ?? job.bytes
  const idle = job.last_activity_ago

  return (
    <div className="grid grid-cols-[6.5rem_1fr_4.5rem_7rem] items-center gap-2 px-3 py-1.5 text-[0.75rem] hover:bg-(--ui-sidebar-surface-background)">
      <span className={cn('truncate font-medium', STATUS_TONE[job.status] ?? 'text-(--ui-text-tertiary)')}>
        {statusLabel(job)}
      </span>

      <div className="min-w-0">
        <div className="truncate text-foreground" title={job.id}>
          {job.name || job.id}
        </div>
        <div className="truncate text-[0.6875rem] text-(--ui-text-quaternary)">
          {[scopeLabel(job), job.cpus ? `${job.cpus}c` : '', job.tail ?? ''].filter(Boolean).join(' · ')}
        </div>
      </div>

      <span className="text-right tabular-nums text-(--ui-text-secondary)">{fmtRcrunDuration(job.elapsed)}</span>

      <span className="text-right tabular-nums text-(--ui-text-tertiary)">
        {running && idle !== null && idle !== undefined
          ? `${fmtRcrunBytes(live)} · ${fmtRcrunDuration(idle)} ago`
          : fmtRcrunBytes(live)}
      </span>
    </div>
  )
}

function Section({
  title,
  jobs,
  hint
}: {
  title: string
  jobs: RcrunJob[]
  hint?: string
}): React.JSX.Element | null {
  if (jobs.length === 0) return null
  return (
    <div>
      <div className="px-3 pt-2 pb-1 text-[0.625rem] tracking-wide text-(--ui-text-quaternary) uppercase">
        {hint ? `${title} · ${hint}` : title}
      </div>
      {jobs.map(job => (
        <JobRow key={job.id} job={job} />
      ))}
    </div>
  )
}

/** Statusbar chip: icon + the one number the user cares about. */
export function RcrunStatusChip(): React.JSX.Element {
  const { data } = useRcrunJobs()
  const agg = data?.agg
  const running = agg?.running ?? 0
  const pending = agg?.pending ?? 0
  const failed = agg?.failed ?? 0

  const label = !data
    ? '—'
    : running
      ? `${running} running`
      : pending
        ? `${pending} queued`
        : failed
          ? `${failed} failed`
          : 'no jobs'

  return (
    <button
      type="button"
      className={cn(
        'flex h-full cursor-pointer items-center gap-1 px-1.5 text-[0.6875rem] [-webkit-app-region:no-drag] hover:text-(--ui-text-secondary)',
        running ? 'text-(--ui-accent)' : failed && !running ? 'text-destructive' : 'text-(--ui-text-tertiary)'
      )}
      data-slot="rcrun-statusbar-chip"
      onClick={toggleRcrunDrawer}
      title="Remote jobs — click to open the drawer"
    >
      <Codicon name="terminal" size="0.75rem" />
      <span>{label}</span>
    </button>
  )
}

/** The drawer itself. Mounted once by the shell so it can overlay any route. */
export function RcrunDrawer(): React.JSX.Element | null {
  const open = useStore($rcrunDrawerOpen)
  const { data, error, isError, isLoading, refetch } = useRcrunJobs()
  const queryClient = useQueryClient()
  const [entered, setEntered] = useState(false)
  const [dispatching, setDispatching] = useState(false)
  const [note, setNote] = useState<string | null>(null)

  // Mount animation: paint once at the closed offset, then transition in.
  useEffect(() => {
    if (!open) {
      setEntered(false)
      return
    }
    const frame = requestAnimationFrame(() => setEntered(true))
    return () => cancelAnimationFrame(frame)
  }, [open])

  useEffect(() => {
    if (!open) return
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setRcrunDrawerOpen(false)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open])

  const close = useCallback(() => setRcrunDrawerOpen(false), [])

  const dispatch = useCallback(async () => {
    setDispatching(true)
    setNote(null)
    try {
      const result = await dispatchRcrun()
      setNote(result.stdout.split('\n').pop() || (result.code === 0 ? 'dispatch ok' : `exit ${result.code}`))
      await refetch()
      queryClient.invalidateQueries({ queryKey: ['rcrun', 'jobs'] })
    } catch (dispatchError) {
      setNote(dispatchError instanceof Error ? dispatchError.message : 'dispatch failed')
    } finally {
      setDispatching(false)
    }
  }, [queryClient, refetch])

  const groups = useMemo(() => {
    const jobs = data?.jobs ?? []
    return {
      running: jobs.filter((job: RcrunJob) => job.status === 'running'),
      pending: [...jobs.filter((job: RcrunJob) => job.status === 'pending')].sort(
        (a, b) => (a.queue_pos ?? 0) - (b.queue_pos ?? 0)
      ),
      attention: jobs.filter((job: RcrunJob) => job.status === 'failed' || job.status === 'verify_failed'),
      recent: jobs.filter((job: RcrunJob) => job.status === 'fetched').slice(0, 6)
    }
  }, [data?.jobs])

  if (!open) return null

  const agg = data?.agg
  const reachability = data?.remote_checked ? (data.remote_ok ? 'remote reachable' : 'remote unreachable') : 'idle'

  return (
    <div className="fixed inset-0 z-[70]" role="dialog" aria-label="Remote jobs">
      <div className="absolute inset-0" onMouseDown={close} />

      <div
        className={cn(
          'absolute right-2 bottom-6 flex w-[min(46rem,calc(100vw-1rem))] flex-col overflow-hidden rounded-md border border-(--ui-stroke-secondary) bg-popover text-popover-foreground shadow-xl transition-all duration-150',
          entered ? 'translate-y-0 opacity-100' : '-translate-y-1 opacity-0'
        )}
        data-slot="rcrun-drawer"
      >
        <div className="flex items-center gap-4 px-3 py-2">
          <Stat label="Running" value={`${agg?.running ?? 0}/${agg?.max_running ?? '—'}`} />
          <Stat label="Queued" value={agg?.pending ?? 0} />
          <Stat label="Done" value={agg?.fetched ?? 0} />
          <Stat label="Failed" value={agg?.failed ?? 0} />
          <div className="flex-1" />
          <div className="flex flex-col items-end gap-0.5 text-[0.6875rem] text-(--ui-text-quaternary)">
            <span className="flex items-center gap-1">
              <span
                className={cn(
                  'size-1.5 rounded-full',
                  data?.remote_checked && data.remote_ok ? 'bg-(--ui-accent)' : 'bg-(--ui-text-quaternary)'
                )}
              />
              {reachability}
            </span>
            <span className="max-w-[16rem] truncate" title={(data?.runs_roots ?? []).join('  ·  ')}>
              {data?.ssh_target ?? ''}
            </span>
          </div>
        </div>

        <div className="h-px shrink-0 bg-(--ui-stroke-secondary)" />

        <div className="min-h-0 flex-1 overflow-y-auto pb-2">
          {isLoading ? (
            <div className="px-3 py-6 text-center text-[0.75rem] text-(--ui-text-quaternary)">Loading…</div>
          ) : isError ? (
            <div className="px-3 py-6 text-center text-[0.75rem] text-destructive">
              {error instanceof Error ? error.message : 'Failed to read jobs'}
            </div>
          ) : (data?.jobs.length ?? 0) === 0 ? (
            <div className="px-3 py-6 text-center text-[0.75rem] text-(--ui-text-quaternary)">
              No jobs yet — submit one with <code className="text-(--ui-text-tertiary)">rcrun submit</code>
            </div>
          ) : (
            <>
              <Section title="Running" jobs={groups.running} />
              <Section title="Queued" jobs={groups.pending} hint="dispatch fills these" />
              <Section title="Needs a human" jobs={groups.attention} />
              <Section title="Recently finished" jobs={groups.recent} />
            </>
          )}
        </div>

        <div className="h-px shrink-0 bg-(--ui-stroke-secondary)" />

        <div className="flex items-center gap-2 px-3 py-2">
          <span className="min-w-0 flex-1 truncate text-[0.6875rem] text-(--ui-text-quaternary)" title={note ?? undefined}>
            {note ?? (data ? `updated ${new Date(data.generated_at * 1000).toLocaleTimeString()}` : '')}
          </span>
          <Button size="sm" variant="ghost" onClick={() => void refetch()}>
            Refresh
          </Button>
          <Button size="sm" variant="secondary" disabled={dispatching} onClick={() => void dispatch()}>
            {dispatching ? 'Dispatching…' : 'Dispatch now'}
          </Button>
        </div>
      </div>
    </div>
  )
}
