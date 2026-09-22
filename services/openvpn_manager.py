"""OpenVPN client control for Sentinel's Tunnel.

WireGuard already had a manager (``agents/vpn_agent/services/wireguard_manager``);
this is its OpenVPN counterpart. OpenVPN needs root to add routes and open a tun
device, so every state change goes through an injected ``run_as_root`` (the real
one raises the macOS authorisation dialog). The client is started daemonised with
a pid and log file so the GUI stays responsive and can report real status and
surface the connection log.

Nothing here fabricates a connection: ``connect`` reports what OpenVPN actually
returned, and ``is_running``/``status`` read the real pid file and process table.
"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
from pathlib import Path
from typing import Callable

from services.runtime_paths import user_data_base

# Injected in tests; the default raises the real admin prompt.
try:  # pragma: no cover - exercised via the real app, mocked in tests
    from agents.vpn_agent.services.privileged import run_as_root as _default_run_as_root
except Exception:  # pragma: no cover
    def _default_run_as_root(script: str, prompt: str, timeout: float = 30):
        return False, "Privileged execution is unavailable."

RunAsRoot = Callable[..., tuple[bool, str]]


def is_openvpn_available() -> bool:
    """True when an OpenVPN client binary is on PATH."""
    return shutil.which("openvpn") is not None


def _run_dir() -> Path:
    path = user_data_base() / "vpn"
    path.mkdir(parents=True, exist_ok=True)
    return path


def pid_file() -> Path:
    return _run_dir() / "openvpn.pid"


def log_file() -> Path:
    return _run_dir() / "openvpn.log"


def _read_pid() -> int | None:
    try:
        text = pid_file().read_text(encoding="utf-8").strip()
        return int(text) if text else None
    except (OSError, ValueError):
        return None


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists but owned by root — that is our daemon
    except OSError:
        return False
    return True


def is_running() -> bool:
    """Real check: our pid file names a live process, or an openvpn is running."""
    pid = _read_pid()
    if pid is not None and _pid_alive(pid):
        return True
    pgrep = shutil.which("pgrep")
    if not pgrep:
        return False
    try:
        return subprocess.run(
            [pgrep, "-x", "openvpn"], capture_output=True, timeout=3
        ).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _quote(text: str) -> str:
    return "'" + str(text).replace("'", "'\\''") + "'"


def connect(config_path: str, *, run_as_root: RunAsRoot = _default_run_as_root) -> dict:
    """Start an OpenVPN client from a .ovpn file, daemonised, as root.

    Returns a structured result; ``success`` means OpenVPN launched, not that the
    tunnel finished negotiating — callers poll ``is_running`` / read ``log_file``.
    """
    result = {"success": False, "output": "", "error": None,
              "log": str(log_file()), "protocol": "OpenVPN"}
    if not is_openvpn_available():
        result["error"] = ("openvpn client not found — install it, e.g. "
                            "`brew install openvpn`.")
        return result
    cfg = Path(config_path).expanduser()
    if not cfg.is_file():
        result["error"] = f"OpenVPN config not found: {config_path}"
        return result
    if is_running():
        result["error"] = "An OpenVPN process is already running. Disconnect first."
        return result

    log = log_file()
    pid = pid_file()
    try:
        log.unlink()
    except OSError:
        pass
    script = (
        f"openvpn --config {_quote(str(cfg))} "
        f"--daemon sentinel-ovpn "
        f"--log {_quote(str(log))} "
        f"--writepid {_quote(str(pid))} "
        f"--verb 3"
    )
    ok, output = run_as_root(script, "Sentinel needs administrator access to start the VPN.")
    result["output"] = output
    result["success"] = ok
    if not ok:
        result["error"] = output or "OpenVPN failed to start."
    return result


def disconnect(*, run_as_root: RunAsRoot = _default_run_as_root) -> dict:
    """Stop the OpenVPN client started by :func:`connect`."""
    result = {"success": False, "output": "", "error": None, "protocol": "OpenVPN"}
    pid = _read_pid()
    if pid is None:
        # Nothing we started is tracked; fall back to a name-scoped stop.
        ok, output = run_as_root(
            "pkill -x openvpn || true",
            "Sentinel needs administrator access to stop the VPN.")
        result["success"] = ok
        result["output"] = output
        if not ok:
            result["error"] = output or "Could not stop OpenVPN."
        return result
    ok, output = run_as_root(
        f"kill {int(pid)} 2>/dev/null || true",
        "Sentinel needs administrator access to stop the VPN.")
    result["success"] = ok
    result["output"] = output
    if ok:
        try:
            pid_file().unlink()
        except OSError:
            pass
    else:
        result["error"] = output or "Could not stop OpenVPN."
    return result


def read_log(max_bytes: int = 8192) -> str:
    """Return the tail of the OpenVPN log, or '' if none."""
    try:
        data = log_file().read_bytes()
    except OSError:
        return ""
    return data[-max_bytes:].decode("utf-8", errors="replace")
