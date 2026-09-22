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

import shutil
import shlex
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


def is_running() -> bool:
    """Whether the tracked Sentinel process exists; not a tunnel-health check."""
    pid = _read_pid()
    return pid is not None and _is_tracked_process(pid)


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


def _is_tracked_process(pid: int) -> bool:
    """Fail closed unless this PID names Sentinel's own OpenVPN command.

    A PID file alone is not identity: PIDs can be stale or reused. Ambiguous
    process arguments (including unquoted spaces from ps) are refused.
    """
    if pid <= 1:
        return False
    try:
        proc = subprocess.run(
            ["/bin/ps", "-p", str(pid), "-o", "command="],
            capture_output=True, text=True, timeout=3,
        )
        args = shlex.split(proc.stdout.strip())
        return (
            proc.returncode == 0 and bool(args)
            and Path(args[0]).name == "openvpn"
            and args[args.index("--daemon") + 1] == "sentinel-ovpn"
            and args[args.index("--writepid") + 1] == str(pid_file())
        )
    except (OSError, subprocess.TimeoutExpired, ValueError, IndexError):
        return False


def disconnect(*, run_as_root: RunAsRoot = _default_run_as_root) -> dict:
    """Request termination only for a verified Sentinel OpenVPN process."""
    result = {"success": False, "output": "", "error": None, "protocol": "OpenVPN"}
    pid = _read_pid()
    if pid is None or not _is_tracked_process(pid):
        result["error"] = (
            "Cannot verify a Sentinel-owned OpenVPN process. Nothing was stopped. "
            "Use the VPN client that started the connection to disconnect it."
        )
        return result
    ok, output = run_as_root(
        f"kill -TERM {pid}",
        "Sentinel needs administrator access to stop the VPN.")
    result["success"] = ok
    result["output"] = output
    # Keep tracking until exit is observed; sending a signal does not prove exit.
    if not ok:
        result["error"] = output or "Could not stop OpenVPN."
    return result


def read_log(max_bytes: int = 8192) -> str:
    """Return the tail of the OpenVPN log, or '' if none."""
    try:
        data = log_file().read_bytes()
    except OSError:
        return ""
    return data[-max_bytes:].decode("utf-8", errors="replace")
