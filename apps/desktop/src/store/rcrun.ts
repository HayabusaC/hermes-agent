import { atom } from 'nanostores'

/**
 * Remote-job drawer (rcrun).
 *
 * A global overlay rather than a pane: it has to work from the chat, from full
 * pages and from split tiles, and it must be dismissible with one click. Kept in
 * the store (not local state) so the statusbar chip, the palette command and the
 * drawer itself all read the same flag.
 */
export const $rcrunDrawerOpen = atom(false)

export function setRcrunDrawerOpen(open: boolean): void {
  $rcrunDrawerOpen.set(open)
}

export function toggleRcrunDrawer(): void {
  $rcrunDrawerOpen.set(!$rcrunDrawerOpen.get())
}
