"""Billing attribution for user-defined providers.

A ``providers:`` entry in config.yaml resolves to the generic ``custom`` runtime route (that is how
the OpenAI-compatible transport is picked). Cost and usage surfaces must still name the provider the
user configured — ``52ai``, ``ucas-artificial-idiot`` — instead of collapsing every custom endpoint
into one ``custom`` line that is only distinguishable by base URL.
"""

from __future__ import annotations

from typing import Any, Optional


def _norm_url(url: Any) -> str:
    return str(url or "").strip().rstrip("/").lower()


def configured_provider_for_base_url(base_url: Any) -> Optional[str]:
    """The ``providers:`` key whose ``base_url``/``api`` matches *base_url*, else ``None``."""
    target = _norm_url(base_url)
    if not target:
        return None
    try:
        from hermes_cli.config import load_config

        providers = (load_config() or {}).get("providers") or {}
    except Exception:
        return None
    if not isinstance(providers, dict):
        return None
    for name, block in providers.items():
        if not isinstance(block, dict):
            continue
        for key in ("base_url", "api", "url"):
            if _norm_url(block.get(key)) == target:
                return str(name)
    return None


def billing_identity(provider: Any, base_url: Any = "") -> str:
    """The provider id a usage row should carry.

    Anything but ``custom`` is already precise. For ``custom`` the configured id for that endpoint
    wins; an unconfigured endpoint (a hand-typed base URL) keeps ``custom``.
    """
    name = str(provider or "").strip().lower()
    if name != "custom":
        return name
    return configured_provider_for_base_url(base_url) or name
