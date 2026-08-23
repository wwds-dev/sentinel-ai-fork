"""
Email OSINT provider — multi-source live lookups.

Zero-cost stack:
  • emailrep.io        → reputation, breach flag, profiles, SPF/DMARC
                         (no key; limit ≈ 10 req/day without key)
  • breachdirectory    → open breach search, no key required

Key-gated (set in .env):
  • haveibeenpwned     → HIBP_API_KEY  — breach names, data classes, pastes ($3.50/mo)

Returns a normalised dict suitable for direct injection into an LLM prompt.
"""

import os
import time
import requests
from dotenv import load_dotenv
from services.runtime_paths import user_data_base

load_dotenv(user_data_base() / ".env", override=False)
HIBP_KEY = os.getenv("HIBP_API_KEY", "")


def _hibp(email: str) -> dict:
    """HaveIBeenPwned v3 — breach list + pastes. Requires HIBP_API_KEY."""
    if not HIBP_KEY:
        return {
            "source": "haveibeenpwned",
            "status": "skipped",
            "reason": "HIBP_API_KEY not set in .env — get key at haveibeenpwned.com/API/Key",
        }
    headers = {
        "hibp-api-key": HIBP_KEY,
        "User-Agent": "SentinelAI-OSINT/1.0",
    }
    try:
        r = requests.get(
            f"https://haveibeenpwned.com/api/v3/breachedaccount/{email}",
            headers=headers,
            params={"truncateResponse": "false"},
            timeout=10,
        )
        if r.status_code == 200:
            breaches = r.json()
        elif r.status_code == 404:
            breaches = []
        else:
            return {"source": "haveibeenpwned", "status": "error", "code": r.status_code}

        time.sleep(1.5)  # HIBP enforces 1 req / 1.5 s

        rp = requests.get(
            f"https://haveibeenpwned.com/api/v3/pasteaccount/{email}",
            headers=headers,
            timeout=10,
        )
        pastes = rp.json() if rp.status_code == 200 else []

        data_classes = sorted({dc for b in breaches for dc in b.get("DataClasses", [])})
        return {
            "source": "haveibeenpwned",
            "status": "ok",
            "breach_count": len(breaches),
            "breach_names": [b.get("Name") for b in breaches],
            "data_classes_exposed": data_classes,
            "paste_count": len(pastes),
        }
    except Exception as e:
        return {"source": "haveibeenpwned", "status": "error", "detail": str(e)[:200]}


def _breachdirectory(email: str) -> dict:
    """BreachDirectory open API — free, no key."""
    try:
        r = requests.get(
            "https://breachdirectory.org/api",
            params={"func": "auto", "term": email},
            headers={"User-Agent": "SentinelAI-OSINT/1.0"},
            timeout=10,
        )
        if r.status_code == 200:
            data = r.json()
            sources = data.get("result", [])
            return {
                "source": "breachdirectory",
                "status": "ok",
                "found": data.get("found", False),
                "result_count": len(sources) if isinstance(sources, list) else 0,
                "sources": sources[:10] if isinstance(sources, list) else [],
            }
        return {"source": "breachdirectory", "status": "error", "code": r.status_code}
    except Exception as e:
        return {"source": "breachdirectory", "status": "error", "detail": str(e)[:200]}


def lookup(email: str) -> dict:
    """
    Return a normalised OSINT dict for an email address.

    Keys:
      type, query, valid_format, reputation (EmailRep payload), error
    """
    email = email.strip()
    domain_part = email.split("@")[-1] if "@" in email else ""
    valid_format = bool(email and "@" in email and "." in domain_part)

    result: dict = {
        "type":         "email",
        "query":        email,
        "valid_format": valid_format,
    }

    if not valid_format:
        result["error"] = "Invalid email format — skipping live lookup."
        return result

    try:
        resp = requests.get(
            f"https://emailrep.io/{email}",
            timeout=10,
            headers={
                "User-Agent": "SentinelAI-OSINT/1.0",
                "Accept":     "application/json",
            },
        )

        if resp.status_code == 200:
            data = resp.json()
            # Pull the most OSINT-relevant fields to the top level for readability
            details = data.get("details", {})
            result["reputation"] = {
                "score":                    data.get("reputation"),          # high/medium/low/none
                "suspicious":               data.get("suspicious"),
                "references":               data.get("references"),          # number of sources
                "blacklisted":              details.get("blacklisted"),
                "malicious_activity":       details.get("malicious_activity"),
                "credentials_leaked":       details.get("credentials_leaked"),
                "credentials_leaked_recent":details.get("credentials_leaked_recent"),
                "data_breach":              details.get("data_breach"),
                "first_seen":               details.get("first_seen"),
                "last_seen":                details.get("last_seen"),
                "domain_reputation":        details.get("domain_reputation"),
                "new_domain":               details.get("new_domain"),
                "days_since_domain_creation": details.get("days_since_domain_creation"),
                "suspicious_tld":           details.get("suspicious_tld"),
                "spam":                     details.get("spam"),
                "free_provider":            details.get("free_provider"),
                "disposable":               details.get("disposable"),
                "deliverable":              details.get("deliverable"),
                "spoofable":                details.get("spoofable"),
                "spf_strict":               details.get("spf_strict"),
                "dmarc_enforced":           details.get("dmarc_enforced"),
                "profiles":                 details.get("profiles", []),     # known platform profiles
            }

        elif resp.status_code == 400:
            result["error"] = "emailrep.io: invalid email or bad request"
        elif resp.status_code == 429:
            result["error"] = (
                "emailrep.io rate limit reached (~10 req/day without API key). "
                "Register at https://emailrep.io for a free key."
            )
        else:
            result["error"] = f"emailrep.io returned HTTP {resp.status_code}"

    except requests.exceptions.Timeout:
        result["error"] = "emailrep.io request timed out (>10 s)"
    except Exception as exc:
        result["error"] = str(exc)[:300]

    # ── Additional sources ──────────────────────────────────────────────────
    result["hibp"]             = _hibp(email)
    result["breachdirectory"]  = _breachdirectory(email)

    # Convenience summary for Bloodhound prompt injector
    breach_hits = 0
    if result["hibp"].get("status") == "ok":
        breach_hits += result["hibp"].get("breach_count", 0)
    if result["breachdirectory"].get("status") == "ok" and result["breachdirectory"].get("found"):
        breach_hits += result["breachdirectory"].get("result_count", 0)

    emailrep_suspicious = (
        result.get("reputation", {}).get("suspicious", False)
        or result.get("reputation", {}).get("credentials_leaked", False)
    )

    result["summary"] = {
        "breach_hits":    breach_hits,
        "suspicious":     emailrep_suspicious,
        "sources_queried": 3,
        "sources_live":   sum(
            1 for s in [result.get("reputation"), result["hibp"], result["breachdirectory"]]
            if s and (isinstance(s, dict) and s.get("status", "ok") not in ("skipped", "error"))
        ),
    }

    return result
