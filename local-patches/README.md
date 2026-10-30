# local-patches — this fork's changes to upstream Hermes

Everything below is applied on top of a clean `NousResearch/hermes-agent` checkout.
Nothing is committed, nothing is pushed: the checkout stays a plain mirror of
upstream `main`, so `git pull` stays a fast-forward and `git stash` is never
needed.

```bash
bash local-patches/apply.sh      # or: powershell -File local-patches/apply.ps1
bash local-patches/verify.sh     # contract in sync, python compiles, tsc
```

Both scripts are idempotent: an already-applied patch reports `already applied`
instead of failing, so a partially patched tree can always be finished or redone.

## Client-only installs (a desktop that only talks to a remote gateway)

Nothing that runs server-side needs to exist on that machine. Apply 0003 (its
generated `gateway-contract.generated.ts` is what the cost UI's types come from),
0004 and 0006:

```bash
SKIP="0001 0002 0005" bash local-patches/apply.sh          # bash
powershell -File local-patches/apply.ps1 -Skip 0001,0002,0005   # Windows
```

0001 is messaging-gateway behaviour (Slack bubbles, channel-bound skills,
platform session cwd) plus the `insights` invoice row — server-side only.
0002 is the provider hooks the server calls. 0005 is a CLI command.

## Building the Windows installer in CI (no local Windows toolchain)

`.github/workflows/desktop-light-nsis.yml` builds the Light client + NSIS
installer on `windows-latest` — the only host shape that can produce the
win32-only natives (`get-windows` binding, `hud-modifier-monitor.exe`).

One-time setup, from the checkout that carries `local-patches/`:

```bash
git checkout -b local/desktop
git add local-patches .github/workflows/desktop-light-nsis.yml
git commit -m "local patches + desktop CI"
git remote add fork https://github.com/<you>/hermes-agent.git   # fork upstream first
git push -u fork local/desktop
```

Then in the fork: **Actions → "I understand my workflows, go ahead and enable
them"** → *desktop-light-nsis* → *Run workflow* (branch `local/desktop`,
optional `feed_url`) → the `hermes-light-nsis` artifact holds the installer,
`latest.yml` and the blockmaps.

The workflow applies the patches at build time, so the branch stays a thin layer
over upstream `main` and `git pull` stays a fast-forward. It typechecks before
packaging, so a broken patch fails in ~5 minutes instead of after a full build.

## What each patch owns

| # | Patch | What it does | Files touched | Upgrade risk |
|---|---|---|---|---|
| 0001 | `platform-turn-behaviour` | Pre-existing local behaviour: `/insights` shows an `Actual (invoiced)` cost bucket; the desktop bubble is cleaned up after a turn; the chat-skill first-turn check; platform sessions keep their own cwd | `agent/insights.py`, `gateway/run_turn*.py`, `gateway/session_authority.py` | medium — `run_turn*.py` churn upstream |
| 0002 | `provider-model-metadata` | Per-model `api_mode`/`base_url` hooks (one provider can serve chat / responses / anthropic), `get_model_pricing()` hook, context/output limits on the wire | `providers/base.py`, `hermes_cli/{providers,runtime_provider,inventory}.py`, `tui_gateway/contracts/config_free_tier_control.py` | medium — these files move often; all hunks are narrow additions |
| 0003 | `usage-analytics` | `analytics.total_cost` (per session `actual || estimated`, then summed), model rows carry provider + cache-write/reasoning tokens, profile-level model resolution | `hermes_cli/web_routers/analytics.py`, `hermes_cli/web_server_profiles.py`, **generated** `gateway-contract.generated.ts` | low — self-contained query change |
| 0004 | `desktop-cost-ui` | Statusbar cost chip + popover (1/7/30 days), model hover panel (context / max output / price), `LOCAL` deployment tag for `hepai/*`, cost row in the command centre, and the backend update track made read-only (status visible, install entry refused: `BACKEND_UPDATE_APPLY_ENABLED`) | `apps/desktop/src/**` (10 files) | medium — React surface churn; all fork-local display logic is in `src/lib/cost-display.ts` |
| 0005 | `sessions-release` | `hermes sessions release <id>`: asks the owning runtime to let go of a live session (`session.close`, else `resume`+`detach`) | `hermes_cli/sessions_release.py` (new) + 2 wiring lines | very low — new module |
| 0006 | `nsis-installer-updates` | NSIS Windows installer target, `hermes://` protocol registration, and a real `WindowsNsisStrategy` so a self-built install can self-update from a generic feed | `apps/desktop/electron/**`, `electron-builder.config.cjs`, `scripts/write-build-stamp.mjs`, `build/installer-protocol.nsh` | low — new file + narrow dispatch |

## Rules that keep this maintainable

1. **Never hand-edit generated files.** `apps/shared/src/gateway-contract.generated.ts`
   comes from `scripts/gen_gateway_contracts.py`; change the pydantic model in
   `tui_gateway/contracts/` and regenerate. `verify.sh` fails if the file differs
   from codegen output.
2. **One fork-local knob, one file.** Currency, rounding and the echoed labels
   live in `apps/desktop/src/lib/cost-display.ts`. Do not reintroduce
   `* 7` or a bare `¥` anywhere else.
3. **New files instead of edits.** 0005 and 0006 are almost entirely new modules
   with two-to-five lines of wiring, which is why they survive upgrades.
4. **Never touch `apps/desktop/build/` without `git add -f`.** That directory is
   gitignored (it holds generated packaging artifacts), so a new NSIS include
   silently drops out of a regenerated patch.
5. **After a `git pull`:** run `apply.sh`, then `verify.sh`. If a patch conflicts,
   fix the file in place, then regenerate just that patch:

   ```bash
   git diff HEAD -- <files of that patch> > local-patches/000N-name.patch
   ```

## Regenerating all patches from the working tree

```bash
git diff HEAD -- agent/insights.py gateway/run_turn*.py gateway/session_authority.py \
  > local-patches/0001-platform-turn-behaviour.patch
```

(The file lists above are the definition of each patch; keep this README and the
lists in step.)
