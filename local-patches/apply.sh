#!/usr/bin/env bash
# Apply every local patch, oldest first. Safe to re-run: already-applied patches
# report "skipped" instead of failing.
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1

# SKIP="0001 0005" selects patches by number prefix. A client-only install (a
# Windows box that only connects to a remote gateway) needs 0004 + 0006 and
# nothing that runs server-side, e.g.:  SKIP="0001 0002 0005" bash apply.sh
skip=" ${SKIP:-} "
status=0
for patch in local-patches/[0-9][0-9][0-9][0-9]-*.patch; do
  name=$(basename "$patch")
  case "$skip" in
    *" ${name%%-*} "*) echo "skipped    $name"; continue ;;
  esac
  printf '%-46s' "$name"
  if git apply --check "$patch" >/dev/null 2>&1; then
    git apply "$patch" && echo "applied"
  elif git apply --check --reverse "$patch" >/dev/null 2>&1; then
    echo "already applied"
  else
    echo "CONFLICT"
    git apply --3way "$patch" >/dev/null 2>&1 || true
    status=1
  fi
done

if [ "$status" -ne 0 ]; then
  echo
  echo "Some patches did not apply. Conflict markers were written where git could"
  echo "three-way merge them; run 'git diff' to inspect, then 'npm run typecheck'"
  echo "(or the Python tests) before building."
fi
exit "$status"
