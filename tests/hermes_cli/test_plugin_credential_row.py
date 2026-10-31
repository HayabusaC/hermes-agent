"""An ``api_key`` registry row may omit env vars when the profile mints its own credential.

``_profile_row`` used to treat "no env vars" as "not a provider at all", which forced
credential-owning plugins (an OAuth/subscription login whose token rotates) to invent a fake
env var just to get a registry row. That fake var also planted a dead "paste key" card in
Settings → Providers → API keys. The row is still needed: the api-key rung is the only rung
that consults ``ProviderProfile.resolve_api_key_secret``, and without a row the ladder walks to
its OpenRouter fallback and spends an unrelated cloud key (#113703).
"""

from __future__ import annotations

from hermes_cli.auth_plugin_providers import _profile_row, profile_owns_runtime_credential
from providers.base import ProviderProfile


class _CredentialOwning(ProviderProfile):
    def resolve_api_key_secret(self):  # pragma: no cover - exercised through _profile_row
        return '{"token":"t"}', "fake_oauth"


class _PlainKeyed(ProviderProfile):
    pass


def _profile(cls, *, env_vars=()):
    return cls(
        name="fake-owned" if cls is _CredentialOwning else "fake-plain",
        display_name="Fake",
        base_url="https://example.test/v1",
        env_vars=tuple(env_vars),
        auth_type="plugin-defined",
        registry_auth_type="api_key",
    )


def test_credential_owning_profile_is_detected():
    assert profile_owns_runtime_credential(_profile(_CredentialOwning)) is True
    assert profile_owns_runtime_credential(_profile(_PlainKeyed)) is False


def test_api_key_row_without_env_vars_needs_an_owned_credential():
    owned = _profile_row(_profile(_CredentialOwning))

    assert owned is not None
    assert owned.auth_type == "api_key"
    assert tuple(owned.api_key_env_vars) == ()
    assert owned.inference_base_url == "https://example.test/v1"

    assert _profile_row(_profile(_PlainKeyed)) is None


def test_declared_env_vars_still_build_a_key_row():
    row = _profile_row(_profile(_CredentialOwning, env_vars=("FAKE_API_KEY",)))

    assert row is not None
    assert tuple(row.api_key_env_vars) == ("FAKE_API_KEY",)
