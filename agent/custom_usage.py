"""Wallet / usage for a user-defined ``providers:`` entry that exposes one.

Several OpenAI-compatible resellers (52ai among them) answer a usage endpoint with a wallet
balance and per-day spend even though their completions carry only token counts. Hermes cannot
price those model ids, so the cost panel would show $0 for a provider the user is visibly paying
for. A `providers:` entry may therefore declare:

    providers:
      my-reseller:
        base_url: https://api.example/v1
        key_env: HERMES_CUSTOM_MY_RESELLER_API_KEY
        usage_url: /v1/usage          # absolute or relative to base_url

and the provider row then reports the balance / today's spend the endpoint returns. Nothing is
hardcoded per vendor: the parser accepts the common shapes and degrades to no usage line.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


def custom_usage_url(provider: str) -> Optional[str]:
    """The absolute usage URL a ``providers:`` entry declares, or None."""
    slug = str(provider or "").strip().lower()
    if not slug:
        return None
    try:
        from hermes_cli.config import load_config

        entry = ((load_config() or {}).get("providers") or {}).get(slug)
    except Exception:  # a broken config must not fail the picker
        return None
    if not isinstance(entry, dict):
        return None
    raw = str(entry.get("usage_url") or "").strip()
    if not raw:
        return None
    if raw.startswith(("http://", "https://")):
        return raw
    base = str(entry.get("base_url") or entry.get("api") or entry.get("url") or "").strip()
    if not base:
        return None
    # "/v1/usage" against "https://host/v1" is still "https://host/v1/usage" on these gateways,
    # so join on the origin and take the path verbatim.
    from urllib.parse import urlsplit, urlunsplit

    parts = urlsplit(base)
    if raw.startswith("/"):
        # Declared as a path on the endpoint's host: "/v1/usage" means exactly that, even when
        # base_url already carries "/v1".
        return urlunsplit((parts.scheme, parts.netloc, raw, "", ""))
    joined = parts.path.rstrip("/") + "/" + raw
    return urlunsplit((parts.scheme, parts.netloc, joined, "", ""))


def custom_provider_currency(provider: str) -> tuple[str, float, float]:
    """``(currency_symbol, amounts_are_cny, usd_per_cny)`` for a ``providers:`` entry.

    Resellers commonly label CNY amounts as "USD" at 1:1 (52ai does: the figures the endpoint
    reports are what the user pays in yuan). ``currency: CNY`` states that, and ``usd_per_cny``
    converts for the USD-denominated ledger (default 1/7.1 ≈ 0.1408).
    """
    slug = str(provider or "").strip().lower()
    entry: dict[str, Any] = {}
    try:
        from hermes_cli.config import load_config

        entry = ((load_config() or {}).get("providers") or {}).get(slug) or {}
    except Exception:
        entry = {}
    if not isinstance(entry, dict):
        entry = {}
    currency = str(entry.get("currency") or "").strip().upper()
    try:
        rate = float(entry.get("usd_per_cny") or 0.0)
    except (TypeError, ValueError):
        rate = 0.0
    if rate <= 0:
        rate = 0.1408
    symbol = "¥" if currency == "CNY" else "$"
    return symbol, currency == "CNY", rate


def custom_provider_credentials(provider: str) -> tuple[str, str]:
    """``(api_key, base_url)`` for a ``providers:`` entry, from its inline key or key_env."""
    slug = str(provider or "").strip().lower()
    try:
        from hermes_cli.config import get_env_value_prefer_dotenv, load_config

        entry = ((load_config() or {}).get("providers") or {}).get(slug) or {}
    except Exception:
        return "", ""
    if not isinstance(entry, dict):
        return "", ""
    key = str(entry.get("api_key") or "").strip()
    if not key:
        key_env = str(entry.get("key_env") or entry.get("api_key_env") or "").strip()
        if key_env:
            try:
                key = str(get_env_value_prefer_dotenv(key_env) or "").strip()
            except Exception:
                key = ""
    base = str(entry.get("base_url") or entry.get("api") or entry.get("url") or "").strip()
    return key, base


def _as_float(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def fetch_custom_provider_usage(provider: str, *, base_url: str = "", api_key: str = "") -> Optional[Any]:
    """Snapshot with wallet details for *provider*, or None when it declares no usable endpoint.

    Text-only on purpose: a wallet balance has no percentage basis, so it rides in ``details``
    (the chip's tooltip) instead of pretending to be a quota window. Read-only and never raises.
    """
    from datetime import UTC, datetime

    import httpx

    from agent.account_usage import AccountUsageSnapshot

    url = custom_usage_url(provider)
    if not url:
        return None
    key = api_key or custom_provider_credentials(provider)[0]
    try:
        resp = httpx.get(url, headers={"Authorization": f"Bearer {key}"} if key else {}, timeout=15.0)
    except httpx.HTTPError:
        return None
    if resp.status_code != 200:
        logger.debug("custom usage %s: HTTP %s", url, resp.status_code)
        return None
    try:
        payload = resp.json()
    except ValueError:
        return None
    if not isinstance(payload, dict):
        return None

    unit = str(payload.get("unit") or "USD").strip() or "USD"
    symbol, amounts_are_cny, usd_per_cny = custom_provider_currency(provider)
    if amounts_are_cny:
        unit = "CNY"
    today = ((payload.get("usage") or {}).get("today") or {}) if isinstance(payload.get("usage"), dict) else {}
    total = ((payload.get("usage") or {}).get("total") or {}) if isinstance(payload.get("usage"), dict) else {}

    details: list[str] = []
    balance = _as_float(payload.get("balance", payload.get("remaining")))
    if balance is not None:
        # details[0] is also the chip's label, so keep it short.
        details.append(f"Wallet {symbol}{balance:.4f} {unit}")
    today_spend = _as_float(today.get("actual_cost", today.get("cost")))
    if today_spend is not None:
        list_cost = _as_float(today.get("cost"))
        requests = today.get("requests")
        line = f"Today {symbol}{today_spend:.4f} {unit}"
        if list_cost is not None and abs(list_cost - today_spend) > 1e-9:
            line += f" (list {symbol}{list_cost:.4f})"
        if isinstance(requests, int):
            line += f" · {requests} req"
        details.append(line)
    total_spend = _as_float(total.get("actual_cost", total.get("cost")))
    if total_spend is not None:
        details.append(f"All time {symbol}{total_spend:.4f} {unit}" + (f" (≈${total_spend * usd_per_cny:.2f})" if amounts_are_cny else ""))
    plan = str(payload.get("planName") or "").strip()
    if plan:
        details.append(f"Plan {plan}")
    if not details:
        return None

    # The model the wallet is mostly spent on is the useful second line; keep the list short.
    stats = payload.get("model_stats")
    if isinstance(stats, list) and stats:
        top = max((s for s in stats if isinstance(s, dict)), key=lambda s: _as_float(s.get("actual_cost")) or 0.0, default=None)
        if isinstance(top, dict) and top.get("model"):
            spend = _as_float(top.get("actual_cost", top.get("cost")))
            if spend is not None:
                details.append(f"Top model {top['model']}: {symbol}{spend:.4f} {unit}")

    return AccountUsageSnapshot(
        provider=str(provider or "").strip().lower(),
        source="custom_usage_api",
        fetched_at=datetime.now(UTC),
        title="Wallet",
        windows=(),
        details=tuple(details),
    )
