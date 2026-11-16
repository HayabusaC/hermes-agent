"""A plugin provider that MINTS its own runtime credential must still get a live catalog.

``_profile_live_catalog`` only probed ``profile.fetch_models`` for ``auth_type == "api_key"``
profiles, so an OAuth/subscription plugin (antigravity: ``auth_type="plugin-defined"``, credential
from ``resolve_api_key_secret``) was pinned to ``fallback_models`` forever — its published catalogue
never reached the picker and the user's model list froze on whatever the plugin shipped, while a
perfectly good ``fetch_models`` override stayed dead code.
"""

from __future__ import annotations

from unittest.mock import patch

import hermes_cli.models as mod
from providers.base import ProviderProfile


class _CredentialOwnedProfile(ProviderProfile):
    """A plugin profile whose token comes from ``resolve_api_key_secret`` (no env var)."""

    def resolve_api_key_secret(self):  # overrides the base hook → profile_owns_runtime_credential
        return '{"token": "tok", "project": "proj"}', "plugin_oauth"

    def credentials_configured(self) -> bool:
        return True

    def fetch_models(self, *, api_key=None, base_url=None, timeout=8.0):
        assert api_key, "the probe must carry the credential the profile minted"
        return ["alpha-new", "beta-new"]


class _PlainPluginProfile(ProviderProfile):
    """No credential seam: nothing to probe with, so the curated list is the answer."""

    def fetch_models(self, *, api_key=None, base_url=None, timeout=8.0):
        raise AssertionError("a profile without a runtime credential must not be probed")


def _live_catalog(profile, *, api_key="tok-key"):
    with patch("providers.get_provider_profile", return_value=profile), \
         patch.object(mod, "_api_key_credentials", return_value=(api_key, profile.base_url)):
        return mod._profile_live_catalog(profile.name)


def test_credential_owned_plugin_profile_is_probed_live():
    profile = _CredentialOwnedProfile(
        name="cred-owned", auth_type="plugin-defined", base_url="https://hub.example",
        fallback_models=("alpha-old", "beta-old"),
    )
    rows = _live_catalog(profile)
    assert rows is not None
    # curated-first picker order: the plugin's shipped ids lead, the live ids follow.
    assert list(rows) == ["alpha-old", "beta-old", "alpha-new", "beta-new"]


def test_credential_owned_profile_without_a_key_serves_its_curated_list():
    profile = _CredentialOwnedProfile(
        name="cred-owned", auth_type="plugin-defined", base_url="https://hub.example",
        fallback_models=("alpha-old",),
    )
    rows = _live_catalog(profile, api_key="")
    assert rows is not None
    assert list(rows) == ["alpha-old"]


def test_plugin_profile_without_a_credential_seam_stays_on_the_curated_list():
    profile = _PlainPluginProfile(
        name="plain-plugin", auth_type="plugin-defined", base_url="https://hub.example",
        fallback_models=("alpha-old", "beta-old"),
    )
    rows = _live_catalog(profile)
    assert rows is not None
    assert list(rows) == ["alpha-old", "beta-old"]
