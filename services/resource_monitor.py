from types import SimpleNamespace

import psutil  # lets Python read system resource information


class ResourceMonitor:
    def __init__(self):
        self.previous = None  # stores the previous snapshot so we can detect whether values are rising or falling

    def _trend(self, current_value: float, previous_value: float | None, tolerance: float = 0.5) -> str:
        if previous_value is None:
            return "→ stable"  # first reading has no earlier value to compare against

        if current_value > previous_value + tolerance:
            return "↑ rising"  # value increased beyond tolerance
        if current_value < previous_value - tolerance:
            return "↓ falling"  # value decreased beyond tolerance
        return "→ stable"  # small changes are treated as stable

    def _level(self, value: float, yellow_at: float, red_at: float) -> str:
        if value >= red_at:
            return "red"  # heavy/problematic usage
        if value >= yellow_at:
            return "yellow"  # caution zone
        return "green"  # comfortable zone

    @staticmethod
    def _read(reader, fallback):
        """Return one optional system reading without breaking the desktop UI.

        Some macOS environments deny individual sysctl calls even though the
        rest of psutil works. Resource figures are helpful telemetry, not a
        reason to prevent Sentinel from starting.
        """
        try:
            return reader()
        except (OSError, RuntimeError, NotImplementedError):
            return fallback

    def snapshot(self):
        empty_memory = SimpleNamespace(percent=0.0, used=0, total=0, available=0)
        empty_swap = SimpleNamespace(percent=0.0, used=0, total=0)

        vm = self._read(psutil.virtual_memory, empty_memory)
        sm = self._read(psutil.swap_memory, empty_swap)
        cpu = self._read(lambda: psutil.cpu_percent(interval=0.2), 0.0)

        battery = self._read(psutil.sensors_battery, None)
        battery_percent = battery.percent if battery else None  # battery percentage or None
        battery_plugged = battery.power_plugged if battery else None  # charging state or None

        previous = self.previous  # keep previous snapshot for trend calculations

        snapshot = {
            "cpu_percent": cpu,
            "cpu_trend": self._trend(cpu, previous["cpu_percent"] if previous else None, tolerance=1.0),
            "cpu_level": self._level(cpu, yellow_at=50.0, red_at=80.0),
            "cpu_benchmark": "50% caution · 80% heavy",

            "ram_percent": vm.percent,
            "ram_used_gb": round(vm.used / (1024 ** 3), 2),
            "ram_total_gb": round(vm.total / (1024 ** 3), 2),
            "ram_available_gb": round(vm.available / (1024 ** 3), 2),
            "ram_trend": self._trend(vm.percent, previous["ram_percent"] if previous else None, tolerance=0.5),
            "ram_level": self._level(vm.percent, yellow_at=70.0, red_at=85.0),
            "ram_benchmark": "70% caution · 85% heavy",

            "swap_percent": sm.percent,
            "swap_used_gb": round(sm.used / (1024 ** 3), 2),
            "swap_total_gb": round(sm.total / (1024 ** 3), 2),
            "swap_trend": self._trend(sm.percent, previous["swap_percent"] if previous else None, tolerance=0.5),
            "swap_level": self._level(sm.percent, yellow_at=20.0, red_at=50.0),
            "swap_benchmark": "20% caution · 50% heavy",

            "battery_percent": battery_percent,
            "battery_plugged": battery_plugged,
            "battery_level": (
                "green" if battery_percent is None else
                "red" if (battery_percent <= 20 and not battery_plugged) else
                "yellow" if (battery_percent <= 40 and not battery_plugged) else
                "green"
            ),
            "battery_note": (
                "Plugged in" if battery_percent is not None and battery_plugged else
                "On battery" if battery_percent is not None else
                "Battery unavailable"
            )
        }

        self.previous = snapshot  # store current snapshot for the next comparison
        return snapshot
