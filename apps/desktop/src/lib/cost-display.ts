// cost-display.ts — the ONE place a fork-local money decision lives.
//
// Hermes stores and reports USD everywhere (usage rows, analytics totals).
// This fork displays CNY for the cost surfaces, so the conversion and the
// labels sit here instead of being re-derived in each component: an upgrade
// that touches the usage panel or the command center leaves exactly one small
// file to re-check, and no duplicated `* 7` can drift apart.

/** Display-only FX. Not used in any accounting path. */
export const USD_TO_CNY = 7

/** The currency mark the cost surfaces print. */
export const CURRENCY_MARK = '¥'

/** `¥12.34` for a positive USD amount, an em dash otherwise. */
export function cnyFromUsd(usd: number | null | undefined): string {
  const value = Number(usd)

  if (!Number.isFinite(value) || value <= 0) {
    return '—'
  }

  return `${CURRENCY_MARK}${(value * USD_TO_CNY).toFixed(2)}`
}

/** Component labels for the cost surfaces. They live here, not in the locale
 *  bundles: those are typed against `en`, so a fork-local key would have to be
 *  translated across every shipped locale. */
export const COST_LABELS = {
  cost: '费用',
  todayCost: '今日费用',
  usageAndCost: 'Usage & cost'
} as const
