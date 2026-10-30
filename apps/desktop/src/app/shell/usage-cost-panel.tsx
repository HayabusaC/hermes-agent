import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'

import { getUsageAnalytics } from '@/api/models'
import { cnyFromUsd } from '@/lib/cost-display'
import { BarChart3 } from '@/lib/icons'
import { cn } from '@/lib/utils'

const PERIODS = [1, 7, 30] as const

type Period = (typeof PERIODS)[number]

const compact = (n: number | null | undefined): string => {
  const v = Number(n) || 0

  if (Math.abs(v) >= 1e9) return `${(v / 1e9).toFixed(2)}B`
  if (Math.abs(v) >= 1e6) return `${(v / 1e6).toFixed(2)}M`
  if (Math.abs(v) >= 1e3) return `${(v / 1e3).toFixed(1)}k`

  return String(v)
}

const yuan = cnyFromUsd

const costOf = (estimated: number | null | undefined, actual: number | null | undefined): number => {
  const billed = Number(actual) || 0

  return billed > 0 ? billed : Number(estimated) || 0
}

/** Today's spend for the status-bar chip (invoice first, else the estimate). */
export function useTodayUsageLabel(): string {
  const { data } = useQuery({
    queryFn: () => getUsageAnalytics(1),
    queryKey: ['usage-cost', 1],
    refetchInterval: 120_000,
    staleTime: 60_000
  })

  // The gateway already resolves invoice-first per session; re-deriving it from
  // per-day sums would swap a whole day to its invoiced subtotal.
  const total = Number(data?.totals?.total_cost) || 0

  return yuan(total)
}

export function UsageCostIcon() {
  return <BarChart3 className="size-3" />
}

/** The status-bar popover: periods 1/7/30, token + cost detail per model. */
export function UsageCostPanel() {
  const [period, setPeriod] = useState<Period>(1)
  const { data, isFetching } = useQuery({
    queryFn: () => getUsageAnalytics(period),
    queryKey: ['usage-cost', period],
    staleTime: 30_000
  })

  const totals = data?.totals
  const rows = data?.by_model ?? []
  const total = Number(totals?.total_cost) || rows.reduce(
    (sum, row) => sum + costOf(row.estimated_cost, row.actual_cost),
    0
  )

  return (
    <div className="flex w-[560px] flex-col gap-2 p-2 text-xs">
      <div className="flex items-center gap-1">
        <span className="text-[11px] font-semibold text-(--ui-text-secondary)">用量与费用</span>
        <span className="flex-1" />
        {PERIODS.map(value => (
          <button
            className={cn(
              'rounded-[5px] border px-1.5 py-px text-[10px] transition-colors',
              period === value
                ? 'border-transparent bg-primary text-primary-foreground'
                : 'border-(--ui-stroke-secondary) text-(--ui-text-secondary)'
            )}
            key={value}
            onClick={() => setPeriod(value)}
            type="button"
          >
            {value}天
          </button>
        ))}
        {isFetching ? <span className="text-[10px] text-(--ui-text-quaternary)">…</span> : null}
      </div>

      <div className="flex gap-4 text-[11px] text-(--ui-text-secondary)">
        <span>输入 {compact(totals?.total_input)}</span>
        <span>输出 {compact(totals?.total_output)}</span>
        <span>缓存读 {compact(totals?.total_cache_read)}</span>
        <span className="font-semibold">费用 {yuan(total)}</span>
      </div>

      <div className="border-t border-(--ui-stroke-secondary)" />

      <table className="w-full border-collapse text-[11px]">
        <thead>
          <tr className="text-(--ui-text-quaternary)">
            <th className="py-0.5 pr-2 text-left font-medium">模型</th>
            <th className="py-0.5 pr-2 text-left font-medium">provider</th>
            <th className="py-0.5 pr-2 text-right font-medium">输入</th>
            <th className="py-0.5 pr-2 text-right font-medium">缓存读</th>
            <th className="py-0.5 pr-2 text-right font-medium">缓存写</th>
            <th className="py-0.5 pr-2 text-right font-medium">输出</th>
            <th className="py-0.5 pr-2 text-right font-medium">费用</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(row => (
            <tr className="text-(--ui-text-secondary)" key={row.model + (row.provider || '')}>
              <td className="max-w-[220px] truncate py-0.5 pr-2 font-mono">{row.model}</td>
              <td className="py-0.5 pr-2 text-(--ui-text-quaternary)">{row.provider || '—'}</td>
              <td className="py-0.5 pr-2 text-right tabular-nums">{compact(row.input_tokens)}</td>
              <td className="py-0.5 pr-2 text-right tabular-nums">{compact(row.cache_read_tokens)}</td>
              <td className="py-0.5 pr-2 text-right tabular-nums">{compact(row.cache_write_tokens)}</td>
              <td className="py-0.5 pr-2 text-right tabular-nums">{compact(row.output_tokens)}</td>
              <td className="py-0.5 pr-2 text-right tabular-nums">{yuan(costOf(row.estimated_cost, row.actual_cost))}</td>
            </tr>
          ))}
        </tbody>
      </table>

      {!rows.length ? <div className="text-[10px] text-(--ui-text-quaternary)">该区间没有记录</div> : null}
    </div>
  )
}
