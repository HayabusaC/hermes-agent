// Hermes Light carries no agent runtime: these tests hold the one decision the
// main process keys every local-runtime path on — a light payload never
// resolves, spawns, installs or repairs a local backend, and the first-run gate
// still parks boot so the only answer offered is a remote.
import assert from 'node:assert/strict'

import { test } from 'vitest'

import {
  isFirstRunGateKind,
  isLightPayload,
  isRemoteOnlyBackendKind,
  LIGHT_REMOTE_ONLY_KIND,
  refuseLocalRuntime
} from './light-remote-only'

test('only the light payload is remote-only', () => {
  assert.equal(isLightPayload('light'), true)
  assert.equal(isLightPayload('bundled'), false)
  assert.equal(isLightPayload('bootstrap'), false)
  assert.equal(isLightPayload(undefined), false)
  assert.equal(isLightPayload(null), false)
})

test('the remote-only sentinel is its own kind, not bootstrap-needed', () => {
  assert.equal(isRemoteOnlyBackendKind(LIGHT_REMOTE_ONLY_KIND), true)
  assert.equal(isRemoteOnlyBackendKind('bootstrap-needed'), false)
  assert.equal(isRemoteOnlyBackendKind('python'), false)
})

test('the first-run gate parks both a local install and a remote-only artifact', () => {
  // bootstrap-needed: the choice is install-locally vs connect a remote.
  assert.equal(isFirstRunGateKind('bootstrap-needed'), true)
  // remote-only: the choice is a remote, and nothing else.
  assert.equal(isFirstRunGateKind(LIGHT_REMOTE_ONLY_KIND), true)
  // A resolved backend boots straight away — no gate.
  assert.equal(isFirstRunGateKind('python'), false)
  assert.equal(isFirstRunGateKind('command'), false)
  assert.equal(isFirstRunGateKind(undefined), false)
})

test('a local-runtime refusal is explicit and machine-readable', () => {
  assert.deepEqual(refuseLocalRuntime(), { ok: false, error: 'light-remote-only', remoteOnly: true })
})
