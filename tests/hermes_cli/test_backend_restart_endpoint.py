"""``POST /api/backend/restart`` — restart the backend process, not the messaging gateway.

The route only asks systemd for the restart: the unit's stop phase takes the process answering the
request down, so the child must be detached and the response written first. These cases pin the two
honest refusals (no service manager, no passwordless sudo) and the spawn shape.
"""

import asyncio

import pytest
from fastapi import HTTPException

from hermes_cli.web_routers import actions

UNIT = "hermes-dashboard.service"


def _call():
    return asyncio.run(actions.restart_backend())


def test_refuses_a_backend_no_service_manager_can_restart(monkeypatch):
    monkeypatch.delenv("INVOCATION_ID", raising=False)

    with pytest.raises(HTTPException) as exc:
        _call()

    assert exc.value.status_code == 409
    assert exc.value.detail["error"] == "backend_not_managed"


def test_refuses_without_passwordless_sudo_for_the_unit(monkeypatch):
    monkeypatch.setenv("INVOCATION_ID", "8f0e1d2c")
    monkeypatch.setattr(actions, "_backend_systemd_unit", lambda: UNIT)
    probes = []

    def _deny(probe):
        probes.append(probe)
        return False

    monkeypatch.setattr("hermes_cli.update_cmd_fleet._sudo_noninteractive_ok", _deny)

    with pytest.raises(HTTPException) as exc:
        _call()

    assert exc.value.status_code == 403
    assert exc.value.detail["error"] == "backend_restart_needs_root"
    assert UNIT in " ".join(str(part) for part in exc.value.detail["detail"].split("'"))
    # The probe names the exact command it is about to elevate (a scoped NOPASSWD entry only
    # answers that shape).
    assert probes == [["-l", "--", "systemctl", "restart", UNIT]]


def test_asks_a_detached_child_for_the_restart(monkeypatch):
    monkeypatch.setenv("INVOCATION_ID", "8f0e1d2c")
    monkeypatch.setattr(actions, "_backend_systemd_unit", lambda: UNIT)
    monkeypatch.setattr("hermes_cli.update_cmd_fleet._sudo_noninteractive_ok", lambda probe: True)
    spawned = {}

    class _Proc:
        pid = 4242

    def _popen(argv, **kwargs):
        spawned["argv"] = argv
        spawned["kwargs"] = kwargs
        return _Proc()

    monkeypatch.setattr(actions.subprocess, "Popen", _popen)

    assert _call() == {"ok": True, "pid": 4242, "unit": UNIT}
    assert spawned["argv"] == ["sudo", "-n", "systemctl", "restart", UNIT]
    # Detached, or the unit's stop phase would take the requester down with it mid-restart.
    assert spawned["kwargs"]["start_new_session"] is True


def test_the_unit_is_read_from_this_process_cgroup(tmp_path, monkeypatch):
    cgroup = tmp_path / "cgroup"
    cgroup.write_text("0::/system.slice/hermes-dashboard.service\n", encoding="utf-8")
    monkeypatch.setattr(actions, "Path", lambda _p: cgroup, raising=False)

    assert actions._backend_systemd_unit() == UNIT
