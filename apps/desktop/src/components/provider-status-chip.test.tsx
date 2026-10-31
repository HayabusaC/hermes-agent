import type { ModelOptionProvider, ProviderUsageAccount } from '@hermes/shared'
import { fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'

import { I18nProvider } from '@/i18n'
import { accountResetMs } from '@/lib/provider-limit'

import { ProviderStatusChip } from './provider-status-chip'

const NOW = Date.parse('2026-10-05T15:00:00Z')
const iso = (minutes: number) => new Date(NOW + minutes * 60_000).toISOString()

const account = (index: number, limited: boolean): ProviderUsageAccount & { label: string } => ({
  id: String(index),
  label: `Subscription ${index + 1}`,
  state: limited ? 'limited' : 'ready',
  resets_at: limited ? iso(30 + index) : null,
  windows: [{ label: 'Session', used_percent: limited ? 100 : 20, resets_at: iso(30 + index) }]
})

const provider = (accounts: ProviderUsageAccount[]): ModelOptionProvider => ({
  slug: 'openai-codex',
  name: 'OpenAI Codex',
  models: ['gpt-5.4'],
  // An older single-account observation must never become a pool-wide percentage.
  usage: { windows: [{ label: 'Session', used_percent: 100, resets_at: iso(30) }], accounts }
})

const view = (row: ModelOptionProvider) => (
  <I18nProvider configClient={null} initialLocale="en">
    <ProviderStatusChip provider={row} />
  </I18nProvider>
)

afterEach(() => vi.useRealTimers())

it('keeps a mixed pool usable and exposes each account rather than a provider-wide empty gauge', async () => {
  vi.spyOn(Date, 'now').mockReturnValue(NOW)
  const accounts = Array.from({ length: 10 }, (_, i) => account(i, i === 0))
  const row = provider(accounts)
  const { container } = render(view(row))
  const chip = screen.getByText('1/10 accounts limited')

  expect(screen.queryByText(/Limited until|0% left/)).toBeNull()
  expect(container.querySelector('[aria-hidden]')).toBeNull()
  expect(accountResetMs(row, NOW)).toBeNull()
  fireEvent.pointerMove(chip, { pointerType: 'mouse' })
  const tip = await screen.findByRole('tooltip')

  for (const entry of accounts) {
    expect(within(tip).getByText(entry.label)).toBeTruthy()
  }

  expect(tip.textContent).toContain('Limited until')
  expect(tip.textContent).toContain('80% left')
  // The bar is visual only; the exact state stays in text for screen readers.
  expect(tip.querySelectorAll('span[aria-hidden="true"]')).toHaveLength(accounts.length)
})

it('only presents a pool-wide wall when every account is limited, preserving unknown and expired states', () => {
  vi.spyOn(Date, 'now').mockReturnValue(NOW)
  const accounts = Array.from({ length: 10 }, (_, i) => account(i, true))
  const { rerender } = render(view(provider(accounts)))

  expect(screen.getByText(/Limited until/)).toBeTruthy()
  // Usage reporting never turns into a model-selection gate.
  expect(accountResetMs(provider(accounts), NOW)).toBeNull()

  accounts[9] = { ...accounts[9]!, state: 'unknown', windows: [], resets_at: null }
  rerender(view(provider([...accounts])))
  expect(screen.getByText('9/10 accounts limited')).toBeTruthy()
  expect(screen.queryByText(/Limited until/)).toBeNull()

  vi.spyOn(Date, 'now').mockReturnValue(NOW + 60 * 60_000)
  rerender(view(provider([...accounts])))
  expect(screen.getByText('10 accounts')).toBeTruthy()
  expect(screen.queryByText(/Limited until|accounts limited/)).toBeNull()
})

it('always shows a subscription window, without claiming a comfortable plan is running out', async () => {
  vi.spyOn(Date, 'now').mockReturnValue(NOW)
  const row: ModelOptionProvider = {
    slug: 'antigravity',
    name: 'Google Antigravity',
    models: ['gemini-3.8-flash-high'],
    usage: {
      windows: [
        { label: 'Gemini Models · weekly', used_percent: 4, resets_at: iso(1440) },
        { label: 'Claude and GPT models · weekly', used_percent: 0, resets_at: iso(2000) }
      ]
    }
  }

  render(view(row))
  const chip = screen.getByText(/96% left/)
  fireEvent.pointerMove(chip, { pointerType: 'mouse' })
  const tip = await screen.findByRole('tooltip')

  expect(tip.textContent).toContain('Gemini Models · weekly: 96% left')
  expect(tip.textContent).toContain('Claude and GPT models · weekly: 100% left')
  // 96% remaining is information, not a warning.
  expect(tip.textContent).not.toContain('close to its usage limit')
})

it('adds the near-limit header once the tightest window is low', async () => {
  vi.spyOn(Date, 'now').mockReturnValue(NOW)
  const row: ModelOptionProvider = {
    slug: 'openai-codex',
    name: 'OpenAI Codex',
    models: ['gpt-5.4'],
    usage: { windows: [{ label: 'Weekly', used_percent: 88, resets_at: iso(600) }] }
  }

  render(view(row))
  const chip = screen.getByText(/12% left/)
  fireEvent.pointerMove(chip, { pointerType: 'mouse' })
  const tip = await screen.findByRole('tooltip')

  expect(tip.textContent).toContain('OpenAI Codex is close to its usage limit.')
  expect(tip.textContent).toContain('Weekly: 12% left')
})
