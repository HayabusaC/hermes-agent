#!/usr/bin/env bash
# Check that the applied tree is internally consistent:
#   1. the generated gateway contract matches what codegen produces
#   2. every patched Python file still compiles
#   3. (if node_modules exists) the desktop app typechecks
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1

PY="${PYTHON:-python3}"
fail=0

echo "== gateway contract"
before=$(git hash-object apps/shared/src/gateway-contract.generated.ts)
"$PY" scripts/gen_gateway_contracts.py >/dev/null 2>&1 || { echo "   codegen failed (is the venv active?)"; fail=1; }
after=$(git hash-object apps/shared/src/gateway-contract.generated.ts)
if [ "$before" = "$after" ]; then echo "   in sync"; else echo "   REGENERATED — commit the new file"; fail=1; fi

echo "== python syntax"
for f in agent/insights.py gateway/run_turn.py gateway/run_turn_prepare.py gateway/session_authority.py \
         providers/base.py hermes_cli/providers.py hermes_cli/runtime_provider.py hermes_cli/inventory.py \
         hermes_cli/web_routers/analytics.py hermes_cli/web_server_profiles.py \
         hermes_cli/sessions_release.py hermes_cli/sessions_cmd.py hermes_cli/subcommands/sessions.py \
         tui_gateway/contracts/config_free_tier_control.py; do
  "$PY" -m py_compile "$f" || { echo "   FAILED $f"; fail=1; }
done
echo "   done"

echo "== desktop typecheck"
if [ -d apps/desktop/node_modules ]; then
  (cd apps/desktop && npx tsc -p tsconfig.json --noEmit) || fail=1
else
  echo "   skipped (apps/desktop/node_modules missing)"
fi

exit "$fail"
