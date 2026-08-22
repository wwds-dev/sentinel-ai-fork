from types import SimpleNamespace

import services.resource_monitor as resource_monitor
from services.resource_monitor import ResourceMonitor


def _raise_oserror():
    raise OSError("system statistic unavailable")


def test_snapshot_survives_unavailable_optional_system_statistics(monkeypatch):
    monkeypatch.setattr(resource_monitor.psutil, "virtual_memory", _raise_oserror)
    monkeypatch.setattr(resource_monitor.psutil, "swap_memory", _raise_oserror)
    monkeypatch.setattr(resource_monitor.psutil, "cpu_percent", lambda **_: _raise_oserror())
    monkeypatch.setattr(resource_monitor.psutil, "sensors_battery", _raise_oserror)

    snapshot = ResourceMonitor().snapshot()

    assert snapshot["cpu_percent"] == 0.0
    assert snapshot["ram_total_gb"] == 0.0
    assert snapshot["swap_total_gb"] == 0.0
    assert snapshot["battery_percent"] is None
    assert snapshot["battery_note"] == "Battery unavailable"


def test_snapshot_keeps_available_readings(monkeypatch):
    monkeypatch.setattr(
        resource_monitor.psutil,
        "virtual_memory",
        lambda: SimpleNamespace(percent=25.0, used=2 * 1024**3,
                                total=8 * 1024**3, available=6 * 1024**3),
    )
    monkeypatch.setattr(
        resource_monitor.psutil,
        "swap_memory",
        lambda: SimpleNamespace(percent=10.0, used=1 * 1024**3,
                                total=10 * 1024**3),
    )
    monkeypatch.setattr(resource_monitor.psutil, "cpu_percent", lambda **_: 12.0)
    monkeypatch.setattr(
        resource_monitor.psutil,
        "sensors_battery",
        lambda: SimpleNamespace(percent=75.0, power_plugged=True),
    )

    snapshot = ResourceMonitor().snapshot()

    assert snapshot["cpu_percent"] == 12.0
    assert snapshot["ram_used_gb"] == 2.0
    assert snapshot["swap_used_gb"] == 1.0
    assert snapshot["battery_note"] == "Plugged in"
