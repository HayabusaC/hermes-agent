"""Intel GPU facts for the status-bar readout (Linux, i915/xe).

NVIDIA answers through ``nvidia-smi``. Intel's equivalent, ``intel_gpu_top``,
drives i915 perf/OA counters — it needs CAP_PERFMON (or root) and
``perf_event_paranoid <= 1``, which an unprivileged 5 s status-bar poll cannot
assume (this host runs with ``perf_event_paranoid = 4``). What IS readable
without privileges is sysfs:

* the card's PCI identity — so the panel can name the adapter at all,
* ``gt_cur_freq_mhz`` / ``gt_max_freq_mhz`` — the GT clock,
* ``power/rc6_residency_ms`` — accumulated render-engine idle time.

Utilization is therefore derived, not measured per engine: ``1 - idle`` over the
sampling window. RC6 counts the whole GT, so every client rendering on this
machine (any container included) is in the number, and an idle desktop reads
~0-1 %. It is an honest approximation with one known blind spot: a busy display
plane that never wakes the render engine (plain desktop compositing can hit
this) still reads idle.

Absent sysfs interface (old i915, hardware without RC6, non-Linux) each field
simply degrades to None — never an exception the caller has to catch.
"""

from __future__ import annotations

import logging
import re
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_DRM_ROOT = Path("/sys/class/drm")
_PCI_IDS = (Path("/usr/share/hwdata/pci.ids"), Path("/usr/share/misc/pci.ids"))
_INTEL_VENDOR = "0x8086"

# One sample per card: (rc6_ms, monotonic_at_read, last_utilization, last_name).
# The endpoint is polled every few seconds, so the delta between calls IS the
# window — no sleeping inside a request, no extra sampler process.
_sample: dict[str, tuple[float, float, float | None, tuple[str, str] | None]] = {}

# First call has no previous sample to subtract from. Sampling twice over this
# gap costs one short sleep once per process, and the panel gets a number on its
# first poll instead of a dash that looks like "no GPU".
_FIRST_SAMPLE_GAP_S = 0.3


def _read(path: Path) -> str | None:
    try:
        text = path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return None
    return text or None


def _read_int(path: Path) -> int | None:
    raw = _read(path)
    if raw is None:
        return None
    try:
        return int(raw, 0)
    except ValueError:
        return None


def _pci_name(vendor: str, device: str) -> tuple[str, str] | None:
    """(vendor name, device name) from pci.ids, or None when the table is absent."""
    want_vendor = int(vendor, 16)
    want_device = int(device, 16)
    for path in _PCI_IDS:
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        vendor_name: str | None = None
        in_vendor = False
        for line in lines:
            if not line or line.startswith("#"):
                continue
            if not line.startswith("\t"):
                # "^8086  Intel Corporation"
                head, _, name = line.partition("  ")
                try:
                    current = int(head.strip(), 16)
                except ValueError:
                    in_vendor = False
                    continue
                in_vendor = current == want_vendor
                if in_vendor:
                    vendor_name = name.strip()
                continue
            if not in_vendor:
                continue
            fields = line.strip()
            head, _, name = fields.partition("  ")
            try:
                device_id = int(head, 16)
            except ValueError:
                continue
            if device_id == want_device:
                return (vendor_name or "Intel", name.strip())
        return None
    return None


def _card(root: Path) -> tuple[Path, str, str] | None:
    """(card dir, vendor, device) for the first Intel display adapter."""
    try:
        cards = sorted(p for p in root.glob("card[0-9]*") if p.name[4:].isdigit())
    except OSError:
        return None
    found: list[tuple[Path, str, str]] = []
    for card in cards:
        vendor = _read(card / "device" / "vendor")
        device = _read(card / "device" / "device")
        if vendor is None or device is None:
            continue
        if vendor.lower() != _INTEL_VENDOR:
            continue
        found.append((card, vendor.lower(), device.lower()))
    if not found:
        return None
    # The boot display is the one a user means; otherwise the first card.
    for entry in found:
        if (_read(entry[0] / "device" / "boot_vga") or "") == "1":
            return entry
    return found[0]


def _utilization(card: Path) -> float | None:
    """Percent of the sampling window the GT spent awake, from RC6 residency."""
    rc6 = _read_int(card / "power" / "rc6_residency_ms")
    if rc6 is None:
        return None

    key = str(card)
    now = time.monotonic()
    previous = _sample.get(key)
    if previous is None:
        time.sleep(_FIRST_SAMPLE_GAP_S)
        rc6_after = _read_int(card / "power" / "rc6_residency_ms")
        now_after = time.monotonic()
        if rc6_after is None:
            return None
        previous = (float(rc6), now, None, None)
        rc6, now = rc6_after, now_after

    last_rc6, last_at, last_util, _ = previous
    elapsed_ms = (now - last_at) * 1000.0
    util = last_util
    # Under ~40 ms the counter's 1 ms granularity dominates the delta; keep the
    # previous answer rather than reporting a rounding artifact.
    if elapsed_ms >= 40.0:
        idle_ms = max(0.0, float(rc6) - last_rc6)
        util = round(max(0.0, min(100.0, 100.0 * (1.0 - idle_ms / elapsed_ms))), 1)
    return util


def facts() -> dict[str, Any]:
    """``gpu_name`` / ``gpu_util_percent`` / ``gpu_mhz`` for the Intel adapter, or {}.

    Keys match what ``_nvidia_smi_facts`` publishes, so the caller merges either
    vendor into the same payload. ``vram_used_bytes`` is deliberately absent: an
    Intel iGPU has no per-adapter memory figure (it is UMA, budgeted elsewhere).
    """
    found = _card(_DRM_ROOT)
    if found is None:
        return {}
    card, vendor, device = found

    named = _pci_name(vendor, device)
    name = named[1] if named else f"Intel GPU ({vendor}:{device})"

    util = _utilization(card)

    clock = _read_int(card / "gt_cur_freq_mhz")
    clock_max = _read_int(card / "gt_max_freq_mhz")

    _sample[str(card)] = (
        float(_read_int(card / "power" / "rc6_residency_ms") or 0),
        time.monotonic(),
        util,
        named,
    )

    out: dict[str, Any] = {"gpu_name": name, "gpu_util_percent": util}
    if clock is not None:
        out["gpu_mhz"] = clock
        if clock_max is not None:
            out["gpu_mhz_max"] = clock_max
    return out


def reset_cache() -> None:
    """Drop the sampling state (tests, and a rail that moved to another adapter)."""
    _sample.clear()
