"""``hermes sessions release``: give a live session back to the store.

A live session is owned by exactly one runtime (``gateway/session_authority.py``).
While it is live, another client that wants it (local TUI, another gateway, a
resumed CLI) is refused with ``permission_denied`` — the owner never yields, and
killing the whole gateway was the only way out.

This command asks the *owner* to close it through the existing ``session.close``
RPC (``tui_gateway/methods_session.py``), which pops the in-memory session and
finalizes its row with ``end_reason="manual_release"``. Afterwards every client
can resume it normally.

It never STARTS a gateway: with no ready owner nothing is live, so there is
nothing to release.
"""

from __future__ import annotations

import asyncio
import sqlite3
import sys
from pathlib import Path
from typing import Any, Optional

RELEASE_END_REASON = "manual_release"


def _home() -> Path:
    from hermes_constants import get_hermes_home

    return Path(get_hermes_home())


def _db_path() -> Path:
    return _home() / "state.db"


def _lookup(target: str) -> Optional[dict[str, Any]]:
    """Stored row for *target*: exact id, then id prefix, then exact title."""
    db = _db_path()
    if not db.exists():
        return None
    try:
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=10)
        conn.row_factory = sqlite3.Row
    except Exception:
        return None
    try:
        for sql, params in (
            ("SELECT id, source, title, message_count, ended_at FROM sessions WHERE id = ?", (target,)),
            ("SELECT id, source, title, message_count, ended_at FROM sessions WHERE id LIKE ? ORDER BY started_at DESC LIMIT 1",
             (f"{target}%",)),
            ("SELECT id, source, title, message_count, ended_at FROM sessions WHERE title = ? ORDER BY started_at DESC LIMIT 1",
             (target,)),
        ):
            row = conn.execute(sql, params).fetchone()
            if row is not None:
                return dict(row)
        return None
    except Exception:
        return None
    finally:
        conn.close()


def _print_row(row: dict[str, Any]) -> None:
    title = (row.get("title") or "").strip() or "(untitled)"
    print(f"  id       {row['id']}")
    print(f"  title    {title}")
    print(f"  source   {row.get('source') or '?'}")
    print(f"  messages {row.get('message_count') or 0}")
    print(f"  ended    {'yes' if row.get('ended_at') else 'no (live or orphaned)'}")


def _ready_owner():
    """The ready gateway endpoint serving this home, or None (never starts one)."""
    try:
        from hermes_cli.gateway_runtime import discover_gateway_endpoint

        discovery = discover_gateway_endpoint(_home(), timeout=5)
    except Exception:
        return None
    return discovery.endpoint if getattr(discovery, "state", "") == "ready" else None


async def _release(row: dict[str, Any]) -> dict[str, Any]:
    """Ask the owner to let go, using whichever primitive that runtime serves.

    * stdio/TUI gateways serve ``session.close`` (pops the record, finalizes).
    * the composed gateway (what ``hermes dashboard``/``serve`` runs) does not:
      it exposes attach/detach, so a viewer that CLOSES the conversation detaches
      with ``end_reason`` — the owner then ends the row once no viewer is left.
    """
    from hermes_cli.gateway_client import GatewayRPCError, connect_gateway

    async with connect_gateway(endpoint=_ready_owner()) as client:
        try:
            return await client.rpc("session.close", session_id=row["id"])
        except GatewayRPCError as exc:
            if "unknown_method" not in str(exc) and "unknown method" not in str(exc):
                raise
        snapshot = await client.rpc("session.resume", session_id=row["id"])
        subscription = snapshot.get("subscription_id")
        if not subscription:
            raise RuntimeError("owner attached the session but returned no subscription id")
        return await client.rpc(
            "session.detach",
            session_id=snapshot.get("session_id") or row["id"],
            subscription_id=subscription,
            end_reason=RELEASE_END_REASON,
        )


def cmd_release(args) -> int:
    target = (getattr(args, "session", "") or "").strip()
    if not target:
        print("usage: hermes sessions release <session-id|title>", file=sys.stderr)
        return 2
    row = _lookup(target)
    if row is None:
        print(f"No session found matching '{target}'.", file=sys.stderr)
        return 2

    print("Session to release:")
    _print_row(row)
    if row.get("ended_at"):
        print("Already ended — nothing is holding it; any client can resume it.")
        return 0

    endpoint = _ready_owner()
    if endpoint is None:
        print("No gateway is running for this install, so nothing is live.")
        print("If the row is an orphan, the next gateway start finalizes it (startup orphan sweep).")
        return 0
    if getattr(args, "dry_run", False):
        print("Dry run: would ask the owning gateway to close it (nothing was changed).")
        return 0
    if not getattr(args, "yes", False):
        if not sys.stdin.isatty():
            print("Refusing to release without confirmation on a non-interactive stdin; pass --yes.", file=sys.stderr)
            return 2
        try:
            if input("Release it now? [y/N] ").strip().lower() not in {"y", "yes"}:
                print("Cancelled; nothing was released.")
                return 1
        except EOFError:
            return 1

    try:
        result = asyncio.run(_release(row))
    except Exception as exc:  # noqa: BLE001 - report the owner's refusal verbatim
        print(f"Release refused by the owner: {exc}", file=sys.stderr)
        return 3

    payload = result or {}
    acted = bool(payload.get("closed") if "closed" in payload else payload.get("detached"))
    after = _lookup(row["id"]) or {}
    ended = bool(after.get("ended_at"))
    if not acted:
        print(f"Not live on this gateway: {row['id']}")
        return 0
    if ended:
        print(f"Released and finalized: {row['id']}")
        print("Any client (TUI/CLI/desktop) can resume it now.")
        return 0
    # Detach only finalizes once the caller was the LAST viewer: another attached
    # client (or a turn still running there) keeps the row live.
    print(f"Detached this client, but the session is still live: {row['id']}")
    print("Another viewer or a running turn still holds it — close that client (or let its turn finish),")
    print("or stop the owning runtime, then retry.")
    return 4


def add_release_parser(sessions_subparsers) -> None:
    parser = sessions_subparsers.add_parser(
        "release",
        help="Hand a LIVE session back to the store so another client can resume it",
        description=(
            "A live session is owned by one runtime; another client resuming it is refused with "
            "permission_denied. This asks the owner to close it (session.close, end_reason="
            f"{RELEASE_END_REASON}) without stopping the gateway."
        ),
    )
    parser.add_argument("session", help="Session ID (or id prefix, or exact title)")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be released and exit")
    parser.add_argument("--yes", "-y", action="store_true", help="Skip the confirmation prompt")
    parser.set_defaults(func=cmd_release)
