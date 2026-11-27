import { act, render, renderHook, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { $localModelsEnabled } from '@/store/local-models-flag'
import { $statusbarHiddenIds, STATUSBAR_HIDDEN_BY_DEFAULT } from '@/store/statusbar-prefs'

// The poll fires getLocalHardware() every 5s while the item is shown; the
// backend spawns nvidia-smi per poll, so a hidden window must stop polling
// entirely and resume on visibilitychange (#120262).
const { getLocalHardware, hardwareFixture } = vi.hoisted(() => {
  const hardwareFixture = {
    gpu_name: 'NVIDIA Test GPU',
    gpu_util_percent: 10,
    // Plain multiplication, not `8 << 30`: a left shift is int32, so 8/16/32 GB
    // silently become 0 and every meter reads as an empty machine.
    vram_total_bytes: 8 * 2 ** 30,
    vram_used_bytes: 1 * 2 ** 30,
    vram_usable_bytes: 6 * 2 ** 30,
    ram_total_bytes: 32 * 2 ** 30,
    ram_available_bytes: 16 * 2 ** 30,
    // Intel path: utilization may be unknown, the clock usually is not.
    gpu_mhz: 300,
    gpu_mhz_max: 950,
    uma: false
  }

  return { hardwareFixture, getLocalHardware: vi.fn().mockResolvedValue(hardwareFixture) }
})

vi.mock('@/hermes', () => ({ getLocalHardware }))

import { useSystemResourcesStatusbarItem } from './system-resources-statusbar'

describe('system-resources statusbar polling', () => {
  afterEach(() => {
    getLocalHardware.mockReset()
    getLocalHardware.mockResolvedValue(hardwareFixture)
    vi.restoreAllMocks()
    $statusbarHiddenIds.set([...STATUSBAR_HIDDEN_BY_DEFAULT])
    $localModelsEnabled.set(true)
  })

  // The menu is a snapshot of the item at read time: wait for the first poll to
  // land (the outer label stops reading "Resources…") before taking it.
  async function renderMenu() {
    const { result } = await renderShown()

    await waitFor(() => expect(result.current.label).toMatch(/^RAM /))

    const content = result.current.menuContent

    render(<div>{typeof content === 'function' ? content(() => {}) : content}</div>)
  }

  async function renderShown() {
    $localModelsEnabled.set(true)
    $statusbarHiddenIds.set([])

    const { result, unmount } = renderHook(() => useSystemResourcesStatusbarItem())

    // Mount poll, plus nothing scheduled while the window is visible-but-idle
    // beyond the immediate one (POLL_MS is 5s; the fake timers below avoid it).
    await waitFor(() => expect(getLocalHardware).toHaveBeenCalled())

    return { result, unmount }
  }

  it('does not poll while the document is hidden', async () => {
    vi.spyOn(document, 'hidden', 'get').mockReturnValue(true)

    // Mounted while hidden: the mount poll bails out, so no call is expected —
    // give the effect a tick and assert the spawn never happened.
    $localModelsEnabled.set(true)
    $statusbarHiddenIds.set([])
    const { unmount } = renderHook(() => useSystemResourcesStatusbarItem())
    await act(async () => {})

    expect(getLocalHardware).not.toHaveBeenCalled()

    // Even the visibilitychange resume path must stay quiet while hidden.
    await act(async () => {
      document.dispatchEvent(new Event('visibilitychange'))
    })

    expect(getLocalHardware).not.toHaveBeenCalled()
    unmount()
  })

  it('resumes polling when the window becomes visible again', async () => {
    vi.spyOn(document, 'hidden', 'get').mockReturnValue(true)

    $localModelsEnabled.set(true)
    $statusbarHiddenIds.set([])
    const { unmount } = renderHook(() => useSystemResourcesStatusbarItem())
    await act(async () => {})
    expect(getLocalHardware).not.toHaveBeenCalled()

    vi.spyOn(document, 'hidden', 'get').mockReturnValue(false)
    await act(async () => {
      document.dispatchEvent(new Event('visibilitychange'))
    })

    await waitFor(() => expect(getLocalHardware).toHaveBeenCalledTimes(1))
    unmount()
  })

  it('stops polling and removes the listener on unmount', async () => {
    const { unmount } = await renderShown()
    getLocalHardware.mockClear()

    unmount()

    await act(async () => {
      document.dispatchEvent(new Event('visibilitychange'))
    })

    expect(getLocalHardware).not.toHaveBeenCalled()
  })

  it('shows the GPU clock in the panel when the adapter reports one', async () => {
    await renderMenu()

    expect(await screen.findByText('GPU clock')).toBeTruthy()
    expect(screen.getByText('300 / 950 MHz')).toBeTruthy()
  })

  it('paints GPU utilization only when the adapter measures it', async () => {
    getLocalHardware.mockResolvedValue({ ...hardwareFixture, gpu_util_percent: 63 })

    await renderMenu()

    expect(await screen.findByText('GPU utilization')).toBeTruthy()
    expect(screen.getByText('63%')).toBeTruthy()
  })

  it('omits the utilization row entirely when no counter is available', async () => {
    // The Intel iGPU case: a named adapter and a clock, no perf access at all.
    getLocalHardware.mockResolvedValue({ ...hardwareFixture, gpu_util_percent: null })

    await renderMenu()

    expect(await screen.findByText('GPU clock')).toBeTruthy()
    expect(screen.queryByText('GPU utilization')).toBeNull()
    expect(screen.queryByText('—')).toBeNull()
  })

  it('carries RAM usage alone in the outer label, whatever else the host reports', async () => {
    const { result } = await renderShown()

    // Same shape the polling tests use: 16G of 32G resident, plus a GPU block.
    await waitFor(() => expect(result.current.label).toBe('RAM 16G/32G'))
    expect(result.current.label).not.toMatch(/GPU|CPU|°C|rpm|load/i)
  })
})
