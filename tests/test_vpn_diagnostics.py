"""Tunnel's diagnostics stay read-only and external checks remain opt-in."""

from __future__ import annotations

from types import SimpleNamespace
import json

from services import vpn_diagnostics as diagnostics


def _completed(stdout="", stderr="", returncode=0):
    return SimpleNamespace(stdout=stdout, stderr=stderr, returncode=returncode)


def _local_fakes(monkeypatch):
    monkeypatch.setattr(diagnostics.Path, "exists", lambda _self: True)
    monkeypatch.setattr(
        diagnostics.shutil,
        "which",
        lambda name: f"/usr/local/bin/{name}" if name in {"route", "openvpn", "pgrep"} else None,
    )
    monkeypatch.setattr(diagnostics.wireguard_manager, "is_wg_available", lambda: True)
    monkeypatch.setattr(diagnostics.wireguard_manager, "is_wg_quick_available", lambda: True)
    monkeypatch.setattr(diagnostics.wireguard_manager, "list_active_tunnels", lambda: ["utun7"])
    monkeypatch.setattr(diagnostics.dns_check, "get_system_dns_servers", lambda: ["10.0.0.53"])

    def fake_run(command, timeout=8):
        if command[-3:] == ["-n", "get", "default"]:
            return _completed("gateway: 10.0.0.1\ninterface: utun7\n")
        if command[-2:] == ["show", "interfaces"]:
            return _completed("utun7\n")
        if command[-1] == "latest-handshakes":
            return _completed("peer-one\t1700000000\n")
        if command[-1] == "transfer":
            return _completed("peer-one\t2048\t4096\n")
        if command[-2:] == ["-x", "openvpn"]:
            return _completed(returncode=1)
        raise AssertionError(f"unexpected command: {command}")

    monkeypatch.setattr(diagnostics, "_run", fake_run)


def test_local_check_never_contacts_external_services(monkeypatch):
    _local_fakes(monkeypatch)
    contacted = []
    monkeypatch.setattr(
        diagnostics.public_ip, "get_public_ip", lambda: contacted.append("ip")
    )
    monkeypatch.setattr(
        diagnostics.latency, "measure_latency", lambda: contacted.append("latency")
    )

    report = diagnostics.collect_vpn_diagnostics(include_external=False)

    assert contacted == []
    assert report.external_checked is False
    assert report.active_tunnels == ["utun7"]
    assert report.route["interface"] == "utun7"
    assert report.tunnel_stats["utun7"]["received"] == 2048
    assert "does not prove" in report.sections()[-1][1]


def test_external_check_is_explicit_and_structured(monkeypatch):
    _local_fakes(monkeypatch)
    monkeypatch.setattr(diagnostics.public_ip, "get_public_ip", lambda: "203.0.113.10")
    monkeypatch.setattr(
        diagnostics.latency,
        "measure_latency",
        lambda: {"latency_ms": 22.5, "method": "icmp", "status": "OK"},
    )

    report = diagnostics.collect_vpn_diagnostics(include_external=True)

    assert report.external_checked is True
    assert report.public_ip == "203.0.113.10"
    sections = {title: body for title, body, _mono in report.sections()}
    assert "22.5 ms" in sections["Optional external checks"]
    assert "203.0.113.10" in report.as_text()


def test_cancellation_prevents_optional_external_calls(monkeypatch):
    _local_fakes(monkeypatch)
    contacted = []
    monkeypatch.setattr(
        diagnostics.public_ip, "get_public_ip", lambda: contacted.append("ip")
    )

    report = diagnostics.collect_vpn_diagnostics(
        include_external=True, should_cancel=lambda: True
    )

    assert report.cancelled is True
    assert contacted == []
    assert "stopped" in report.summary.lower()


def test_wireguard_status_does_not_request_dump_or_private_keys(monkeypatch):
    _local_fakes(monkeypatch)
    commands = []
    original_run = diagnostics._run

    def recording_run(command, timeout=8):
        commands.append(command)
        return original_run(command, timeout)

    monkeypatch.setattr(diagnostics, "_run", recording_run)
    diagnostics.collect_vpn_diagnostics()

    joined = " ".join(" ".join(command) for command in commands)
    assert " dump" not in joined
    assert "private" not in joined.lower()
    assert "latest-handshakes" in joined
    assert "transfer" in joined


def test_profile_catalog_prefers_live_state_without_writing(monkeypatch, tmp_path):
    live = tmp_path / "vpn_profiles.json"
    live.write_text(json.dumps({
        "profiles": [{
            "name": "Travel VPS", "endpoint": "vpn.example.test",
            "port": 51820, "interface": "wg3", "private_key": "must-not-leak",
        }],
        "active_profile": "Travel VPS",
    }))
    seed = tmp_path / "seed.json"
    seed.write_text(json.dumps({"profiles": [], "active_profile": ""}))
    before = live.read_bytes()
    monkeypatch.setattr(diagnostics.vpn_paths, "profiles_file", lambda: live)
    monkeypatch.setattr(diagnostics, "PROFILE_SEED", seed)

    catalog = diagnostics.load_vpn_profile_catalog()

    assert catalog.active_profile == "Travel VPS"
    assert catalog.profiles[0]["interface"] == "wg3"
    assert "private_key" not in catalog.profiles[0]
    assert live.read_bytes() == before


def test_report_discards_secret_profile_fields(monkeypatch):
    _local_fakes(monkeypatch)
    report = diagnostics.collect_vpn_diagnostics(selected_profile={
        "name": "Travel VPS", "endpoint": "vpn.example.test",
        "port": 51820, "interface": "utun7", "private_key": "must-not-leak",
    })

    assert "private_key" not in report.selected_profile
    assert "must-not-leak" not in report.as_text()


def test_invalid_profile_catalog_shape_is_reported(monkeypatch, tmp_path):
    live = tmp_path / "vpn_profiles.json"
    live.write_text("[]")
    monkeypatch.setattr(diagnostics.vpn_paths, "profiles_file", lambda: live)

    catalog = diagnostics.load_vpn_profile_catalog()

    assert catalog.profiles == ()
    assert "JSON object" in catalog.error


def test_selected_profile_is_compared_with_detected_tunnel(monkeypatch):
    _local_fakes(monkeypatch)
    profile = {
        "name": "Travel VPS", "endpoint": "vpn.example.test",
        "port": 51820, "interface": "utun7",
    }

    report = diagnostics.collect_vpn_diagnostics(selected_profile=profile)

    comparison = next(
        body for title, body, _mono in report.sections()
        if title == "Selected profile comparison"
    )
    assert "Selected tunnel is active" in comparison
    assert "Default route matches" in comparison
    assert "vpn.example.test:51820" in comparison


def test_profile_mismatch_produces_plain_language_next_steps(monkeypatch):
    _local_fakes(monkeypatch)
    profile = {
        "name": "Unfinished VPS", "endpoint": "0.0.0.0",
        "port": 51820, "interface": "wg9",
    }

    report = diagnostics.collect_vpn_diagnostics(selected_profile=profile)
    sections = {title: body for title, body, _mono in report.sections()}

    assert "Selected tunnel is not active" in sections["Selected profile comparison"]
    assert "Endpoint needs attention" in sections["Selected profile comparison"]
    assert "review the Connect preview" in sections["Recommended next steps"]


def test_action_preview_never_invokes_a_process(monkeypatch):
    invoked = []
    monkeypatch.setattr(
        diagnostics, "_run", lambda *a, **k: invoked.append((a, k))
    )
    profile = {
        "name": "Travel VPS", "endpoint": "vpn.example.test",
        "port": 51820, "interface": "wg3",
    }

    preview = diagnostics.build_vpn_action_preview("Restart", profile)

    assert preview.valid is True
    assert preview.commands == (
        "sudo wg-quick down wg3", "sudo wg-quick up wg3",
    )
    assert invoked == []
    assert "Nothing has been executed" in preview.sections()[0][1]


def test_action_preview_rejects_an_unsafe_interface_name():
    preview = diagnostics.build_vpn_action_preview(
        "Connect",
        {"name": "Unsafe", "interface": "wg0; reboot"},
    )

    assert preview.valid is False
    assert preview.commands == ()
    assert "safe WireGuard interface" in preview.error

    option_like = diagnostics.build_vpn_action_preview(
        "Disconnect",
        {"name": "Unsafe", "interface": "--help"},
    )
    assert option_like.valid is False
    assert option_like.commands == ()


def test_openvpn_profile_never_receives_wireguard_commands(monkeypatch):
    _local_fakes(monkeypatch)
    profile = {
        "name": "TCP fallback", "protocol": "OpenVPN TCP/443",
        "endpoint": "vpn.example.test", "port": 443, "interface": "tun0",
    }

    report = diagnostics.collect_vpn_diagnostics(selected_profile=profile)
    comparison = next(
        body for title, body, _mono in report.sections()
        if title == "Selected profile comparison"
    )
    recommendations = next(
        body for title, body, _mono in report.sections()
        if title == "Recommended next steps"
    )
    preview = diagnostics.build_vpn_action_preview("Connect", profile, report)

    assert "OpenVPN is not running" in comparison
    assert "WireGuard tools" not in recommendations
    assert "OpenVPN client" in recommendations
    assert preview.valid is False
    assert preview.commands == ()
    assert "WireGuard profiles only" in preview.error

    unknown = diagnostics.build_vpn_action_preview(
        "Connect",
        {"name": "IKE profile", "protocol": "IKEv2", "interface": "ipsec0"},
    )
    assert unknown.valid is False
    assert unknown.commands == ()
    assert "not supported" in unknown.error
