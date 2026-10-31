"""Actual-cost accounting for a `providers:` entry that reports its own spend.

Hermes cannot price those model ids (they are not in any price table), and deriving a per-token
table from the vendor's numbers does not work either — measured, their ``cost`` is not a clean
linear function of the token counts they report. What IS authoritative is the vendor's own
cumulative ``usage.total.actual_cost``: read it after a call, difference it against the previous
reading, and that delta is the money that call actually cost.

The reading is kept in a small JSON anchor per provider. A delta is dropped (and the anchor reset)
when the vendor's counter goes backwards — a billing reset must not produce a negative charge.
"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

_ANCHOR_LOCK = threading.Lock()


def _anchor_path() -> Path:
    from hermes_constants import get_hermes_home

    return Path(get_hermes_home()) / "cache" / "custom_usage_anchors.json"


def _load_anchors() -> dict[str, Any]:
    try:
        data = json.loads(_anchor_path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _store_anchors(anchors: dict[str, Any]) -> None:
    path = _anchor_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(anchors, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)
    except OSError:
        logger.debug("custom usage anchor write failed", exc_info=True)


def spend_delta(provider: str, current: float) -> float:
    """Difference since the previous reading for *provider*, updating the anchor."""
    slug = str(provider or "").strip().lower()
    with _ANCHOR_LOCK:
        anchors = _load_anchors()
        previous = anchors.get(slug)
        prev_value = None
        if isinstance(previous, dict):
            try:
                prev_value = float(previous.get("actual"))
            except (TypeError, ValueError):
                prev_value = None
        anchors[slug] = {"actual": float(current or 0.0)}
        _store_anchors(anchors)
    if prev_value is None:
        return 0.0
    delta = float(current or 0.0) - prev_value
    # A reset (or a refund) must not book a negative charge.
    return delta if delta > 0 else 0.0


def record_actual_cost(agent: Any, *, session_id: Optional[str] = None,
                       model: Optional[str] = None, wait: bool = False) -> Optional[float]:
    """Read the vendor's spend, book the delta as this call's `actual_cost_usd`, return it.

    Never raises: accounting must not break a turn. ``wait=True`` runs inline (tests).
    """
    try:
        from agent.custom_usage import custom_usage_url, fetch_custom_provider_spend

        provider = str(getattr(agent, "billing_provider", "") or getattr(agent, "provider", "") or "").strip().lower()
        if not provider or custom_usage_url(provider) is None:
            return None
        session_db = getattr(agent, "_session_db", None)
        sid = session_id or getattr(agent, "session_id", None)
        if session_db is None or not sid:
            return None

        def _run() -> Optional[float]:
            # The vendor's counters lag the call by a second or two; reading immediately books a
            # delta of zero and then loses that spend when the anchor moves past it.
            import time as _time

            _time.sleep(6.0)
            spend = fetch_custom_provider_spend(provider)
            if spend is None:
                return None
            delta_native = spend_delta(provider, float(spend["actual"]))
            if delta_native <= 0:
                return 0.0
            # `unit` already reflects `currency: CNY`; the ledger is USD.
            delta_usd = delta_native * float(spend.get("usd_per_cny") or 1.0)
            try:
                session_db.update_token_counts(
                    sid, model=model or getattr(agent, "model", None),
                    billing_provider=provider, billing_base_url=getattr(agent, "base_url", "") or "",
                    actual_cost_usd=delta_usd, cost_status="actual", cost_source="custom_usage_api",
                )
            except TypeError:
                # Older store signature without cost_status/source: the money still lands.
                session_db.update_token_counts(
                    sid, model=model or getattr(agent, "model", None),
                    billing_provider=provider, billing_base_url=getattr(agent, "base_url", "") or "",
                    actual_cost_usd=delta_usd,
                )
            return delta_usd

        if wait:
            return _run()
        threading.Thread(target=_run, name="custom-usage-accounting", daemon=True).start()
        return None
    except Exception:  # accounting is best-effort
        logger.debug("custom actual-cost accounting failed", exc_info=True)
        return None
