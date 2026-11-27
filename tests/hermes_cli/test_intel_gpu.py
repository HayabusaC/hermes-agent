"""Intel GPU readout: RC6-derived utilization, PCI naming, and honest degradation.

The status-bar panel shows these numbers, so the contract under test is "a value
or None, never an exception" plus the arithmetic itself — a wrong utilization is
worse than a missing one.
"""

from pathlib import Path

import pytest

from hermes_cli.local_runtime import intel_gpu


@pytest.fixture(autouse=True)
def _clean_cache():
    intel_gpu.reset_cache()
    yield
    intel_gpu.reset_cache()


def _fake_card(
    root: Path,
    *,
    name: str = "card1",
    vendor: str = "0x8086",
    device: str = "0x5926",
    boot: str | None = "1",
    rc6: int | None = 1000,
) -> Path:
    card = root / name
    (card / "device").mkdir(parents=True)
    (card / "power").mkdir()
    (card / "device" / "vendor").write_text(f"{vendor}\n")
    (card / "device" / "device").write_text(f"{device}\n")
    if boot is not None:
        (card / "device" / "boot_vga").write_text(f"{boot}\n")
    (card / "gt_cur_freq_mhz").write_text("300\n")
    (card / "gt_max_freq_mhz").write_text("950\n")
    if rc6 is not None:
        (card / "power" / "rc6_residency_ms").write_text(f"{rc6}\n")
    return card


def _reader(*, rc6: int | None, clock: int = 300, clock_max: int = 950):
    def read(path):
        text = str(path)
        if text.endswith("rc6_residency_ms"):
            return rc6
        if text.endswith("gt_cur_freq_mhz"):
            return clock
        if text.endswith("gt_max_freq_mhz"):
            return clock_max
        return None

    return read


def test_no_intel_adapter_is_an_empty_answer(tmp_path, monkeypatch):
    monkeypatch.setattr(intel_gpu, "_DRM_ROOT", tmp_path)
    _fake_card(tmp_path, name="card0", vendor="0x10de", device="0x1f02")

    assert intel_gpu.facts() == {}


def test_names_the_adapter_from_pci_ids(tmp_path, monkeypatch):
    _fake_card(tmp_path)
    monkeypatch.setattr(intel_gpu, "_DRM_ROOT", tmp_path)
    monkeypatch.setattr(intel_gpu, "_read_int", _reader(rc6=1000))

    facts = intel_gpu.facts()

    # pci.ids is present on any normal Linux host; without it the fallback still
    # names the adapter rather than hiding the whole readout.
    assert facts["gpu_name"] in {
        "Kaby Lake-U GT3 [Iris Plus Graphics 640]",
        "Intel GPU (0x8086:0x5926)",
    }
    assert facts["gpu_mhz"] == 300
    assert facts["gpu_mhz_max"] == 950


def test_utilization_is_one_minus_the_idle_fraction(tmp_path, monkeypatch):
    card = _fake_card(tmp_path)
    # A window that started 900 ms ago at rc6=1000 and now reads 1450: the GT
    # slept 450 ms of it, so half the window was awake.
    intel_gpu._sample[str(card)] = (1000.0, 9.1, None, None)
    monkeypatch.setattr(intel_gpu.time, "monotonic", lambda: 10.0)
    monkeypatch.setattr(intel_gpu, "_read_int", _reader(rc6=1450))

    assert intel_gpu._utilization(card) == 50.0


def test_a_short_window_keeps_the_previous_answer(tmp_path, monkeypatch):
    card = _fake_card(tmp_path)
    intel_gpu._sample[str(card)] = (1000.0, 10.0, 37.5, None)
    # 10 ms later: the 1 ms counter resolution would turn that into noise.
    monkeypatch.setattr(intel_gpu.time, "monotonic", lambda: 10.01)
    monkeypatch.setattr(intel_gpu, "_read_int", _reader(rc6=1001))

    assert intel_gpu._utilization(card) == 37.5


def test_missing_rc6_still_reports_the_adapter(tmp_path, monkeypatch):
    _fake_card(tmp_path, rc6=None)
    monkeypatch.setattr(intel_gpu, "_DRM_ROOT", tmp_path)
    monkeypatch.setattr(intel_gpu, "_read_int", _reader(rc6=None))

    facts = intel_gpu.facts()

    assert facts["gpu_name"]
    assert facts["gpu_util_percent"] is None


def test_boot_display_wins_over_the_first_card(tmp_path, monkeypatch):
    _fake_card(tmp_path, name="card0", device="0x3e9b", boot="1")
    _fake_card(tmp_path, name="card2", device="0x5926", boot="0")
    monkeypatch.setattr(intel_gpu, "_DRM_ROOT", tmp_path)
    monkeypatch.setattr(intel_gpu, "_read_int", _reader(rc6=1000))

    facts = intel_gpu.facts()

    # card0 (0x3e9b) drives the display; card2's 5926 must not win just by sorting later.
    assert "5926" not in facts["gpu_name"]
    assert "Iris Plus" not in facts["gpu_name"]
