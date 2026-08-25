from providers import domain_lookup


def test_domain_lookup_reports_each_source_and_keeps_errors(monkeypatch):
    monkeypatch.setattr(domain_lookup, "_whois", lambda target: {"registrar": "R"})
    monkeypatch.setattr(domain_lookup, "_dns", lambda target: {"error": "DNS unavailable"})
    monkeypatch.setattr(
        domain_lookup, "_crtsh", lambda target: {"total_unique": 1, "sample": [target]}
    )
    progress = []

    result = domain_lookup.lookup(
        "https://example.com/path",
        on_progress=lambda source, status: progress.append((source, status)),
    )

    assert result["query"] == "example.com"
    assert result["whois"] == {"registrar": "R"}
    assert result["dns"] == {"error": "DNS unavailable"}
    assert [item["status"] for item in result["sources_contacted"]] == [
        "checked", "error", "checked",
    ]
    assert ("WHOIS", "checking") in progress
    assert ("Certificate transparency (crt.sh)", "checked") in progress


def test_cancel_between_sources_returns_partial_result(monkeypatch):
    monkeypatch.setattr(domain_lookup, "_whois", lambda target: {"country": "ZZ"})
    monkeypatch.setattr(
        domain_lookup, "_dns",
        lambda target: (_ for _ in ()).throw(AssertionError("DNS must not run")),
    )
    checks = iter((False, True))

    result = domain_lookup.lookup("192.0.2.1", should_stop=lambda: next(checks))

    assert result["cancelled"] is True
    assert result["whois"] == {"country": "ZZ"}
    assert "dns" not in result


def test_ipv6_is_preserved_and_certificate_lookup_is_skipped(monkeypatch):
    monkeypatch.setattr(domain_lookup, "_whois", lambda target: {})
    monkeypatch.setattr(domain_lookup, "_dns", lambda target: {"AAAA": [target]})
    monkeypatch.setattr(
        domain_lookup, "_crtsh",
        lambda target: (_ for _ in ()).throw(AssertionError("crt.sh must not run")),
    )

    result = domain_lookup.lookup("2001:db8::1")

    assert result["type"] == "ip"
    assert result["query"] == "2001:db8::1"
    assert "certificates" not in result
