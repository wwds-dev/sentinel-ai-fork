from providers import company_lookup, email_lookup, username_lookup


def test_company_lookup_reports_gleif_records_and_progress(monkeypatch):
    class Response:
        status_code = 200

        @staticmethod
        def json():
            return {
                "meta": {"pagination": {"total": 1}},
                "data": [{
                    "id": "LEI123",
                    "attributes": {
                        "lei": "LEI123",
                        "entity": {
                            "legalName": {"name": "Example Limited"},
                            "otherNames": [{"name": "Example"}],
                            "status": "ACTIVE",
                            "jurisdiction": "IE",
                            "registeredAs": "12345",
                            "registeredAt": {"id": "RA000000"},
                            "legalAddress": {
                                "addressLines": ["Main Street"],
                                "city": "Dublin",
                                "country": "IE",
                            },
                        },
                        "registration": {"status": "ISSUED"},
                    },
                }],
            }

    requests = []
    monkeypatch.setattr(
        company_lookup.requests,
        "get",
        lambda *args, **kwargs: requests.append((args, kwargs)) or Response(),
    )
    progress = []
    result = company_lookup.lookup(
        "Example Limited",
        on_progress=lambda source, status: progress.append((source, status)),
    )

    assert requests[0][1]["params"] == {
        "filter[fulltext]": "Example Limited", "page[size]": 10
    }
    assert result["legal_entities"]["total_matches"] == 1
    assert result["legal_entities"]["records"][0]["legal_name"] == "Example Limited"
    assert result["legal_entities"]["records"][0]["legal_address"]["country"] == "IE"
    assert result["sources_contacted"] == [
        {"source": "GLEIF Legal Entity Index", "status": "checked"}
    ]
    assert progress == [
        ("GLEIF Legal Entity Index", "checking"),
        ("GLEIF Legal Entity Index", "checked"),
    ]


def test_company_lookup_can_cancel_before_contact(monkeypatch):
    monkeypatch.setattr(
        company_lookup.requests,
        "get",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not contact GLEIF")),
    )
    result = company_lookup.lookup("Example Limited", should_stop=lambda: True)
    assert result["cancelled"] is True
    assert result["sources_contacted"] == []


def test_username_lookup_reports_urlscan_progress(monkeypatch):
    class Response:
        status_code = 200

        @staticmethod
        def json():
            return {
                "total": 1,
                "results": [{
                    "page": {"url": "https://example.test/u/alice", "domain": "example.test"},
                    "task": {"title": "Alice", "time": "now"},
                }],
            }

    monkeypatch.setattr(username_lookup.requests, "get", lambda *a, **k: Response())
    progress = []
    result = username_lookup.lookup(
        "@alice", on_progress=lambda source, status: progress.append((source, status))
    )
    assert result["query"] == "alice"
    assert result["urlscan"]["unique_domains_found"] == 1
    assert result["sources_contacted"] == [{"source": "URLScan", "status": "checked"}]
    assert progress == [("URLScan", "checking"), ("URLScan", "checked")]


def test_email_lookup_contacts_only_selected_source(monkeypatch):
    called = []
    monkeypatch.setattr(
        email_lookup, "_emailrep",
        lambda email: called.append("emailrep") or {"score": "high"},
    )
    monkeypatch.setattr(
        email_lookup, "_hibp",
        lambda email: called.append("hibp") or {"status": "ok"},
    )
    monkeypatch.setattr(
        email_lookup, "_breachdirectory",
        lambda email: called.append("breachdirectory") or {"status": "ok"},
    )

    result = email_lookup.lookup(
        "analyst@example.com", selected_sources={"emailrep"}
    )
    assert called == ["emailrep"]
    assert result["reputation"] == {"score": "high"}
    assert result["sources_contacted"] == [{"source": "EmailRep", "status": "checked"}]
    assert "hibp" not in result
    assert "breachdirectory" not in result


def test_hibp_without_key_is_recorded_as_skipped_not_contacted(monkeypatch):
    monkeypatch.setattr(email_lookup, "HIBP_KEY", "")
    progress = []
    result = email_lookup.lookup(
        "analyst@example.com",
        selected_sources={"hibp"},
        on_progress=lambda source, status: progress.append((source, status)),
    )
    assert result["sources_contacted"] == []
    assert result["sources_skipped"] == [
        {"source": "Have I Been Pwned", "status": "skipped"}
    ]
    assert progress[-1] == ("Have I Been Pwned", "skipped")


def test_email_lookup_cancellation_preserves_completed_sources(monkeypatch):
    monkeypatch.setattr(email_lookup, "_emailrep", lambda email: {"score": "high"})
    monkeypatch.setattr(
        email_lookup, "_breachdirectory",
        lambda email: (_ for _ in ()).throw(AssertionError("must not run")),
    )
    checks = iter((False, True))
    result = email_lookup.lookup(
        "analyst@example.com",
        selected_sources=("emailrep", "breachdirectory"),
        should_stop=lambda: next(checks),
    )
    assert result["cancelled"] is True
    assert result["reputation"] == {"score": "high"}
    assert len(result["sources_contacted"]) == 1
