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


def test_stale_drop_file_falls_back_to_local(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    home = _home_with_drop(
        tmp_path, {"fan_rpm": 999}, age_s=host_sensors._DROP_MAX_AGE_S + 30
    )
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setattr(host_sensors, "_local_fan", lambda: None)

    facts = host_sensors.read_host_sensors(ttl_s=0)

    assert facts["source"] == "local"
    assert facts["fan_rpm"] is None


def test_unreadable_drop_file_falls_back_to_local(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
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


def test_local_fan_ignores_an_impossible_reading(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    ec = tmp_path / "ec-io"
    ec.write_bytes(bytes(256))  # zeroed EC: no tach
    monkeypatch.setattr(host_sensors, "_EC_IO", str(ec))
    monkeypatch.setattr(host_sensors.glob, "glob", lambda pattern: [])

    assert host_sensors._local_fan() is None


def test_cpu_percent_needs_two_samples(monkeypatch: pytest.MonkeyPatch):
    # Synthetic ticks: two back-to-back reads of the real /proc/stat can land in
    # the same tick, which made the second assertion a coin flip on a busy-CPU
    # host (it failed here every time on an idle one).
    readings = iter(
        [
            "cpu  100 0 100 800 0 0 0 0 0 0\n",
            "cpu  130 0 130 940 0 0 0 0 0 0\n",
        ]
    )
    monkeypatch.setattr(host_sensors, "_read", lambda path: next(readings))
    monkeypatch.setattr(host_sensors, "_prev_stat", None)

    assert host_sensors._local_cpu_percent() is None
    # busy 200→260 of total 1000→1200 = 60/200
    assert host_sensors._local_cpu_percent() == 30.0


def test_cpu_model_reads_the_marketing_name(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        host_sensors,
        "_read",
        lambda path: (
            "processor\t: 0\nmodel\t\t: 142\nmodel name\t: Intel(R) Core(TM) i5-7260U CPU @ 2.20GHz\n"
        ),
    )

    assert host_sensors._local_cpu_model() == "Intel(R) Core(TM) i5-7260U CPU @ 2.20GHz"


def test_cpu_model_never_reports_the_x86_model_number(monkeypatch: pytest.MonkeyPatch):
    # x86 cpuinfo carries a bare `model : 142` (a number). Printing that as the
    # CPU name would be worse than printing nothing.
    monkeypatch.setattr(
        host_sensors, "_read", lambda path: "processor\t: 0\nmodel\t\t: 142\n"
    )

    assert host_sensors._local_cpu_model() is None


def test_cpu_model_falls_back_to_the_arm_board_name(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        host_sensors,
        "_read",
        lambda path: "Hardware\t: BCM2711\nModel\t\t: Raspberry Pi 4 Model B\n",
    )

    assert host_sensors._local_cpu_model() == "BCM2711"


def test_drop_file_without_a_model_still_names_the_cpu(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    # The host-side sampler predates cpu_model; the container's /proc/cpuinfo
    # still knows the physical CPU, so the field is backfilled.
    home = _home_with_drop(tmp_path, {"cpu_util_percent": 12.5, "fan_rpm": 1100})
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setattr(
        host_sensors,
        "_local_cpu_model",
        lambda: "Intel(R) Core(TM) i5-7260U CPU @ 2.20GHz",
    )

    facts = host_sensors.read_host_sensors(ttl_s=0)

    assert facts["source"] == "host"
    assert facts["cpu_model"] == "Intel(R) Core(TM) i5-7260U CPU @ 2.20GHz"


def test_drop_file_model_wins_over_the_local_one(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    home = _home_with_drop(
        tmp_path, {"cpu_model": "AMD Ryzen 9 7950X 16-Core Processor"}
    )
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setattr(host_sensors, "_local_cpu_model", lambda: "wrong")

    assert (
        host_sensors.read_host_sensors(ttl_s=0)["cpu_model"]
        == "AMD Ryzen 9 7950X 16-Core Processor"
    )


def test_result_is_cached_within_the_ttl(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    home = _home_with_drop(tmp_path, {"fan_rpm": 1200})
    monkeypatch.setenv("HERMES_HOME", str(home))

    first = host_sensors.read_host_sensors(ttl_s=60)
    (home / "cache" / "host-sensors.json").write_text(
        json.dumps({"fan_rpm": 1500}), encoding="utf-8"
    )

    assert host_sensors.read_host_sensors(ttl_s=60) is first
    assert host_sensors.read_host_sensors(ttl_s=0)["fan_rpm"] == 1500
