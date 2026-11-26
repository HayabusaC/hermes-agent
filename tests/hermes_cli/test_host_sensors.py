"""host_sensors: drop-file preference, staleness, and the local readers."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from hermes_cli import host_sensors


@pytest.fixture(autouse=True)
def _reset_state(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(host_sensors, "_cache", None)
    monkeypatch.setattr(host_sensors, "_prev_stat", None)
    yield


def _home_with_drop(tmp_path: Path, payload: dict, age_s: float = 0.0) -> Path:
    home = tmp_path / "hermes"
    cache = home / "cache"
    cache.mkdir(parents=True)
    drop = cache / "host-sensors.json"
    drop.write_text(json.dumps(payload), encoding="utf-8")
    if age_s:
        old = time.time() - age_s
        os.utime(drop, (old, old))
    return home


def test_fresh_drop_file_wins(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    home = _home_with_drop(
        tmp_path,
        {"cpu_util_percent": 12.5, "cpu_temp_c": 61, "fan_rpm": 1100, "load1": 0.4},
    )
    monkeypatch.setenv("HERMES_HOME", str(home))

    facts = host_sensors.read_host_sensors(ttl_s=0)

    assert facts["source"] == "host"
    assert facts["fan_rpm"] == 1100
    assert facts["cpu_temp_c"] == 61


def test_stale_drop_file_falls_back_to_local(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    home = _home_with_drop(tmp_path, {"fan_rpm": 999}, age_s=host_sensors._DROP_MAX_AGE_S + 30)
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setattr(host_sensors, "_local_fan", lambda: None)

    facts = host_sensors.read_host_sensors(ttl_s=0)

    assert facts["source"] == "local"
    assert facts["fan_rpm"] is None


def test_unreadable_drop_file_falls_back_to_local(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    home = tmp_path / "hermes"
    (home / "cache").mkdir(parents=True)
    (home / "cache" / "host-sensors.json").write_text("{not json", encoding="utf-8")
    monkeypatch.setenv("HERMES_HOME", str(home))

    assert host_sensors.read_host_sensors(ttl_s=0)["source"] == "local"


def test_local_fan_reads_the_ec_pair(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    ec = tmp_path / "ec-io"
    blob = bytearray(256)
    blob[host_sensors._EC_FAN_REG] = 0xBC  # 1212 little-endian
    blob[host_sensors._EC_FAN_REG + 1] = 0x04
    ec.write_bytes(bytes(blob))
    monkeypatch.setattr(host_sensors, "_EC_IO", str(ec))
    monkeypatch.setattr(host_sensors.glob, "glob", lambda pattern: [])

    assert host_sensors._local_fan() == 0x04BC


def test_local_fan_ignores_an_impossible_reading(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    ec = tmp_path / "ec-io"
    ec.write_bytes(bytes(256))  # zeroed EC: no tach
    monkeypatch.setattr(host_sensors, "_EC_IO", str(ec))
    monkeypatch.setattr(host_sensors.glob, "glob", lambda pattern: [])

    assert host_sensors._local_fan() is None


def test_cpu_percent_needs_two_samples(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(host_sensors, "_prev_stat", None)

    assert host_sensors._local_cpu_percent() is None
    assert isinstance(host_sensors._local_cpu_percent(), float)


def test_result_is_cached_within_the_ttl(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    home = _home_with_drop(tmp_path, {"fan_rpm": 1200})
    monkeypatch.setenv("HERMES_HOME", str(home))

    first = host_sensors.read_host_sensors(ttl_s=60)
    (home / "cache" / "host-sensors.json").write_text(json.dumps({"fan_rpm": 1500}), encoding="utf-8")

    assert host_sensors.read_host_sensors(ttl_s=60) is first
    assert host_sensors.read_host_sensors(ttl_s=0)["fan_rpm"] == 1500
