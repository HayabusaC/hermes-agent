"""The fork's startup platform prune keeps its own allowlist, separate from upstream's.

An upstream sync once collided two same-named-but-different allowlists on the runtime-status
merge: startup passes **bare** platform names this process owns (``own_platforms``), while a
profile rescan passes **profile-qualified** exemption keys inside the drop filter
(``keep_platforms``, upstream's). Sharing one parameter would let a rescan's
``{"alpha:discord"}`` act as the startup allowlist and wipe every bare platform entry, so the
two stay apart and both behaviours are pinned here.
"""
import json

import pytest

from gateway import status as status_mod
from gateway.status import flush_runtime_status, publish_runtime_status, write_runtime_status


@pytest.fixture
def state(tmp_path, monkeypatch):
    path = tmp_path / "gateway_state.json"
    monkeypatch.setattr(status_mod, "_get_runtime_status_path", lambda: path)
    flush_runtime_status()
    yield path
    flush_runtime_status()


def _seed(path, platforms):
    """Write a previous run's verdicts, then load them the way gateway startup does."""
    path.write_text(json.dumps({"kind": "gateway", "platforms": platforms}), encoding="utf-8")
    write_runtime_status(reload_existing=True, gateway_state="starting", wait_timeout=2.0)


def _platforms(path):
    flush_runtime_status()
    return json.loads(path.read_text(encoding="utf-8")).get("platforms") or {}


def test_startup_prune_drops_platforms_a_previous_run_reported(state):
    _seed(state, {
        "telegram": {"state": "fatal", "error_code": "token_rejected"},
        "slack": {"state": "connected"},
        "prof1:discord": {"state": "connected"},
    })

    publish_runtime_status(own_platforms=["slack"])

    # The disabled/rejected telegram entry from an earlier run is gone; the platform this
    # process owns and the profile-scoped entry a multiplexed child wrote stay.
    assert sorted(_platforms(state)) == ["prof1:discord", "slack"]


def test_publishing_without_own_platforms_never_prunes(state):
    _seed(state, {"telegram": {"state": "fatal"}, "slack": {"state": "connected"}})

    publish_runtime_status(active_agents=0)

    assert sorted(_platforms(state)) == ["slack", "telegram"]


def test_empty_own_platforms_drops_every_bare_entry_but_keeps_profile_scoped(state):
    _seed(state, {"telegram": {"state": "fatal"}, "prof1:discord": {"state": "connected"}})

    publish_runtime_status(own_platforms=[])

    assert sorted(_platforms(state)) == ["prof1:discord"]


def test_profile_rescan_keep_list_does_not_act_as_the_startup_allowlist(state):
    _seed(state, {
        "telegram": {"state": "fatal"},
        "alpha:telegram": {"state": "fatal"},
        "alpha:discord": {"state": "connected"},
    })

    # The rescan passes profile-qualified keys here; the bare telegram entry must survive.
    publish_runtime_status(drop_profile_platforms="alpha", keep_platforms={"alpha:discord"})

    platforms = _platforms(state)
    assert "alpha:telegram" not in platforms
    assert platforms["alpha:discord"]["state"] == "connected"
    assert platforms["telegram"]["state"] == "fatal"
