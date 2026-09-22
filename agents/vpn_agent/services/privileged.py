"""
privileged.py — Running one command as root, from a GUI.

Both the kill switch and MAC randomisation need root for a moment. A GUI has
nowhere to show a terminal password prompt, and blocking on one invisibly looks
exactly like a hang, so this tries cached sudo credentials first and falls back
to the native macOS authorisation dialog.

Nothing secret is ever passed through here — firewall rules, interface names,
file paths. That matters because the command is briefly visible in the process
list, which would be unacceptable for anything carrying a key.
"""

from __future__ import annotations

import os
import subprocess

DEFAULT_TIMEOUT = 30


def run(command: list[str], timeout: float = DEFAULT_TIMEOUT) -> tuple[bool, str]:
    """Run a command directly, returning (ok, combined output)."""
    try:
        proc = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return False, "Timed out."
    except OSError as exc:
        return False, str(exc)

    output = (proc.stdout + proc.stderr).strip()
    if proc.returncode == 0:
        return True, output
    if "User canceled" in output or "(-128)" in output:
        return False, "Cancelled."
    return False, output or f"exited {proc.returncode}"


def run_as_root(script: str, prompt: str, timeout: float = DEFAULT_TIMEOUT) -> tuple[bool, str]:
    """
    Run a shell snippet as root.

    Order matters: cached sudo first, because it is silent and does not steal
    focus. The authorisation dialog is only raised when there is no other way,
    so a user who has just run `sudo -v` is never interrupted.
    """
    if os.geteuid() == 0:
        return run(["bash", "-c", script], timeout)

    ok, output = run(["sudo", "-n", "bash", "-c", script], timeout)
    if ok:
        return True, output

    lowered = output.lower()
    if "password" not in lowered and "sudo" not in lowered:
        # A real failure from the command itself, not a missing credential.
        return False, output

    escaped = script.replace("\\", "\\\\").replace('"', '\\"')
    return run(
        [
            "osascript", "-e",
            f'do shell script "{escaped}" with prompt "{prompt}" '
            "with administrator privileges",
        ],
        timeout,
    )
