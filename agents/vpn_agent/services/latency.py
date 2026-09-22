"""
latency.py — Measures latency to a target host using ICMP ping via subprocess.
Falls back to TCP connect timing if ICMP is blocked.
On macOS, the system ping command is used directly.
"""

import subprocess
import time
import socket

# Default ping target — Cloudflare's fast public resolver
DEFAULT_TARGET = "1.1.1.1"

# Number of pings to send per test.
# 2 pings instead of 4 — halves blocking time, still gives a valid average.
DEFAULT_COUNT = 2

# TCP port used for fallback latency test
TCP_PORT = 443

# Timeout for TCP fallback in seconds
TCP_TIMEOUT = 5


def ping_host(host: str = DEFAULT_TARGET, count: int = DEFAULT_COUNT) -> dict:
    """
    Ping a host using the system ping command (macOS compatible).
    Returns a dict with:
      - host: target that was pinged
      - avg_ms: average round-trip time in milliseconds (float or None)
      - packet_loss_pct: percentage of packets lost (float or None)
      - raw_output: last line of ping summary
      - error: error string if ping failed entirely
    """
    result = {
        "host": host,
        "avg_ms": None,
        "packet_loss_pct": None,
        "raw_output": "",
        "error": None,
    }

    try:
        # macOS ping: -c count, -q for quiet summary output only
        cmd = ["ping", "-c", str(count), "-q", host]
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=10,  # 2 pings at ~1s each + headroom; well under close wait
        )

        output = proc.stdout.strip()
        result["raw_output"] = output

        if proc.returncode != 0:
            result["error"] = f"Ping failed (exit {proc.returncode})"
            return result

        # Parse macOS ping summary line:
        # "round-trip min/avg/max/stddev = 12.345/15.678/18.901/2.345 ms"
        for line in output.splitlines():
            if "round-trip" in line or "rtt" in line:
                parts = line.split("=")[-1].strip().split("/")
                if len(parts) >= 2:
                    result["avg_ms"] = float(parts[1])

            # Parse packet loss: "4 packets transmitted, 4 received, 0.0% packet loss"
            if "packet loss" in line:
                for token in line.split(","):
                    if "packet loss" in token:
                        pct_str = token.strip().split("%")[0].strip()
                        result["packet_loss_pct"] = float(pct_str)

    except subprocess.TimeoutExpired:
        result["error"] = "Ping timed out"
    except FileNotFoundError:
        result["error"] = "ping command not found"
    except Exception as e:
        result["error"] = str(e)

    return result


def tcp_latency(host: str = DEFAULT_TARGET, port: int = TCP_PORT) -> dict:
    """
    Measure TCP connect latency as a fallback when ICMP ping is blocked.
    Returns a dict with host, port, latency_ms, and error.
    """
    result = {"host": host, "port": port, "latency_ms": None, "error": None}
    try:
        start = time.monotonic()
        sock = socket.create_connection((host, port), timeout=TCP_TIMEOUT)
        elapsed = (time.monotonic() - start) * 1000  # convert to ms
        sock.close()
        result["latency_ms"] = round(elapsed, 2)
    except Exception as e:
        result["error"] = str(e)
    return result


def measure_latency(host: str = DEFAULT_TARGET) -> dict:
    """
    Try ICMP ping first. If it fails, fall back to TCP latency check.
    Returns a unified dict with:
      - host, method ("icmp" or "tcp"), latency_ms, packet_loss_pct, status, error
    """
    icmp = ping_host(host)

    if icmp["avg_ms"] is not None:
        return {
            "host": host,
            "method": "icmp",
            "latency_ms": round(icmp["avg_ms"], 2),
            "packet_loss_pct": icmp["packet_loss_pct"],
            "status": "OK",
            "error": None,
        }

    # ICMP failed — try TCP fallback
    tcp = tcp_latency(host)
    if tcp["latency_ms"] is not None:
        return {
            "host": host,
            "method": "tcp",
            "latency_ms": tcp["latency_ms"],
            "packet_loss_pct": None,
            "status": "OK (TCP fallback)",
            "error": None,
        }

    return {
        "host": host,
        "method": "none",
        "latency_ms": None,
        "packet_loss_pct": None,
        "status": "Unreachable",
        "error": icmp["error"] or tcp["error"],
    }
