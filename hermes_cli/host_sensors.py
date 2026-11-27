"""CPU / temperature / fan facts for the status-bar resource readout.

Two sources, in order of preference:

1. A sidecar drop file (``$HERMES_HOME/cache/host-sensors.json``) written by
   whatever *can* see the metal — an agent in a container sees its own slice of
   ``/proc/stat`` (lxcfs masks it) and cannot read the ACPI EC at all, so the
   physical host's numbers have to be sampled from outside and dropped here.
   A file younger than ``_DROP_MAX_AGE_S`` wins over local probing.
2. The local machine: a ``/proc/stat`` delta, hwmon core temperatures and the
   first hwmon fan tach (the EC tach pair when no hwmon fan node exists), plus
   the CPU's marketing name (``/proc/cpuinfo``, sysctl or the Windows registry).

The CPU model is the one field the sidecar need not carry: a container's
``/proc/cpuinfo`` still names the physical CPU, so it is backfilled locally when
the drop file omits it.

Everything is best-effort and read-only: each field may be ``None``, and a
missing file, hwmon node or unreadable EC never raises into the endpoint.
"""

from __future__ import annotations

import glob
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

_DROP_MAX_AGE_S = 20.0
_CACHE_TTL_S = 3.0
_EC_IO = "/sys/kernel/debug/ec/ec0/io"
_EC_FAN_REG = 0x13  # little-endian tach pair, identified empirically (Intel NUC EC)
_CORE_SENSORS = ("coretemp", "k10temp", "zenpower", "cpu_thermal")

_lock = threading.Lock()
_cache: tuple[float, dict[str, Any]] | None = None
_prev_stat: tuple[int, int] | None = None  # (busy, total) ticks


def _hermes_home() -> Path:
    env = os.environ.get("HERMES_HOME")
    return Path(env) if env else Path.home() / ".hermes"


def _drop_file() -> Path:
    return _hermes_home() / "cache" / "host-sensors.json"


def _read_drop() -> dict[str, Any] | None:
    path = _drop_file()
    try:
        age = time.time() - path.stat().st_mtime
        if age > _DROP_MAX_AGE_S:
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def _read(path: str) -> str | None:
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read().strip()
    except OSError:
        return None


def _local_cpu_percent() -> float | None:
    global _prev_stat
    raw = _read("/proc/stat")
    if not raw:
        return None
    first = raw.splitlines()[0].split()
    if len(first) < 9 or first[0] != "cpu":
        return None
    try:
        vals = [int(v) for v in first[1:9]]
    except ValueError:
        return None
    busy = sum(vals[:3]) + sum(vals[5:8])
    total = sum(vals)
    pct = None
    with _lock:
        prev = _prev_stat
        _prev_stat = (busy, total)
    if prev is not None and total > prev[1]:
        pct = round(
            max(0.0, min(100.0, 100.0 * (busy - prev[0]) / (total - prev[1]))), 1
        )
    return pct


def _local_temps() -> int | None:
    package = None
    hottest = None
    for hw in glob.glob("/sys/class/hwmon/hwmon*"):
        name = _read(os.path.join(hw, "name"))
        if name not in _CORE_SENSORS:
            continue
        for path in glob.glob(os.path.join(hw, "temp*_input")):
            raw = _read(path)
            if not raw:
                continue
            try:
                celsius = int(raw) / 1000.0
            except ValueError:
                continue
            if not 1 < celsius < 150:  # acpitz reports signed garbage on some boards
                continue
            if package is None and path.endswith("temp1_input"):
                package = celsius
            if hottest is None or celsius > hottest:
                hottest = celsius
    best = package if package is not None else hottest
    return round(best) if best is not None else None


def _local_fan() -> int | None:
    for path in glob.glob("/sys/class/hwmon/hwmon*/fan*_input"):
        raw = _read(path)
        try:
            rpm = int(raw) if raw else 0
        except ValueError:
            continue
        if 0 < rpm < 20000:
            return rpm
    try:
        with open(_EC_IO, "rb") as f:
            blob = f.read(_EC_FAN_REG + 2)
    except OSError:
        return None
    if len(blob) < _EC_FAN_REG + 2:
        return None
    rpm = blob[_EC_FAN_REG] | (blob[_EC_FAN_REG + 1] << 8)
    return rpm if 0 < rpm < 20000 else None


def _local_cpu_model() -> str | None:
    """The CPU's marketing name ("Intel(R) Core(TM) i5-7260U CPU @ 2.20GHz")."""
    # Linux (x86 names it "model name"; ARM boards use Hardware/Model).
    cpuinfo = _read("/proc/cpuinfo")
    if cpuinfo:
        # x86 says "model name", most ARM boards "Hardware"/"Model". Bare "model"
        # is the x86 *number* (e.g. "142"), so it is only trusted when it carries
        # letters — that keeps ARM working without printing "142" on a laptop.
        named, numbered = ("model name", "cpu model", "hardware"), None
        for line in cpuinfo.splitlines():
            key, _, value = line.partition(":")
            key, value = key.strip().lower(), value.strip()
            if not value:
                continue
            if key in named:
                return value
            if (
                key == "model"
                and numbered is None
                and any(ch.isalpha() for ch in value)
            ):
                numbered = value
        if numbered:
            return numbered

    if sys.platform == "darwin":
        try:
            done = subprocess.run(
                ["sysctl", "-n", "machdep.cpu.brand_string"],
                capture_output=True,
                text=True,
                timeout=2,
                check=False,
            )
            name = done.stdout.strip()
            if name:
                return name
        except (OSError, subprocess.SubprocessError):
            pass

    if sys.platform == "win32":
        try:
            import winreg

            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"HARDWARE\DESCRIPTION\System\CentralProcessor\0",
            ) as key:
                name, _ = winreg.QueryValueEx(key, "ProcessorNameString")
            if isinstance(name, str) and name.strip():
                return name.strip()
        except (OSError, ImportError):
            pass

    return None


def _local_mhz() -> int | None:
    values = []
    for path in glob.glob("/sys/devices/system/cpu/cpu[0-9]*/cpufreq/scaling_cur_freq"):
        raw = _read(path)
        if not raw:
            continue
        try:
            values.append(int(raw) / 1000.0)
        except ValueError:
            continue
    return round(sum(values) / len(values)) if values else None


def _local_load1() -> float | None:
    try:
        return round(os.getloadavg()[0], 2)
    except OSError:
        return None


def _local_cores() -> int | None:
    try:
        return os.cpu_count()
    except Exception:  # a probe, never a failure surface
        return None


def read_host_sensors(ttl_s: float = _CACHE_TTL_S) -> dict[str, Any]:
    """Fresh-enough CPU / thermal / fan facts, or ``{}`` when nothing can be read.

    Keys: ``cpu_util_percent``, ``load1``, ``cpu_mhz``, ``cpu_temp_c``, ``fan_rpm``,
    ``cores``, ``cpu_model`` and ``source`` (``"host"`` for the drop file, ``"local"``
    for in-process probing). Cached for ``ttl_s`` so a 5 s status-bar poll costs one probe.
    """
    global _cache
    now = time.monotonic()
    cached = _cache
    if cached is not None and now - cached[0] < ttl_s:
        return cached[1]

    payload = _read_drop()
    if payload is not None:
        if not payload.get("cpu_model"):
            # The sidecar predates this field (and a container still sees the
            # host's /proc/cpuinfo), so fill it in rather than show nothing.
            model = _local_cpu_model()
            if model:
                payload["cpu_model"] = model
        payload.setdefault("source", "host")
        _cache = (now, payload)
        return payload

    local = {
        "cpu_util_percent": _local_cpu_percent(),
        "load1": _local_load1(),
        "cpu_mhz": _local_mhz(),
        "cpu_temp_c": _local_temps(),
        "fan_rpm": _local_fan(),
        "cores": _local_cores(),
        "cpu_model": _local_cpu_model(),
        "source": "local",
    }
    _cache = (now, local)
    return local
