"""
pki.py — A minimal certificate authority for the OpenVPN fallback.

OpenVPN needs a real PKI, which is normally where people give up and copy an
easy-rsa incantation they don't understand. This module builds the same thing
in-process, with three deliberate choices:

  * P-256 elliptic-curve keys, not RSA. Handshakes are faster on a small VPS,
    keys are 32 bytes instead of 2048 bits, and — the practical win — OpenVPN
    can then run `dh none`, so there is no multi-minute Diffie-Hellman parameter
    generation step during install.

  * Extended key usage is pinned on both ends. The server certificate is marked
    serverAuth and the client certificates clientAuth, which lets the client
    assert `remote-cert-tls server`. Without that, anyone holding a *client*
    certificate from your own CA could impersonate your server to your other
    clients.

  * The CA private key stays on this machine. It is written into the site file
    and never shipped to the server, so compromising the VPS does not let an
    attacker mint new client certificates.
"""

from __future__ import annotations

import datetime as dt
import ipaddress

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

CURVE = ec.SECP256R1
CA_VALID_DAYS = 3650      # 10 years — rotating a CA means re-issuing every client
LEAF_VALID_DAYS = 1825    # 5 years
_CLOCK_SKEW = dt.timedelta(minutes=5)


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _private_key_pem(key: ec.EllipticCurvePrivateKey) -> str:
    return key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("ascii")


def _cert_pem(cert: x509.Certificate) -> str:
    return cert.public_bytes(serialization.Encoding.PEM).decode("ascii")


def _load_key(pem: str) -> ec.EllipticCurvePrivateKey:
    key = serialization.load_pem_private_key(pem.encode("ascii"), password=None)
    if not isinstance(key, ec.EllipticCurvePrivateKey):
        raise ValueError("Expected an elliptic-curve private key")
    return key


def _load_cert(pem: str) -> x509.Certificate:
    return x509.load_pem_x509_certificate(pem.encode("ascii"))


def _name(common_name: str, org: str) -> x509.Name:
    return x509.Name(
        [
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, org),
            x509.NameAttribute(NameOID.COMMON_NAME, common_name),
        ]
    )


def create_ca(site_name: str) -> tuple[str, str]:
    """
    Create a self-signed certificate authority for a site.

    Returns (cert_pem, key_pem). The key never leaves this machine.
    """
    key = ec.generate_private_key(CURVE())
    subject = _name(f"{site_name} VPN CA", site_name)
    now = _now()

    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - _CLOCK_SKEW)
        .not_valid_after(now + dt.timedelta(days=CA_VALID_DAYS))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=True,
                crl_sign=True,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False
        )
        .sign(key, hashes.SHA256())
    )
    return _cert_pem(cert), _private_key_pem(key)


def issue_server_cert(
    ca_cert_pem: str,
    ca_key_pem: str,
    common_name: str,
    endpoint_host: str = "",
) -> tuple[str, str]:
    """Issue a serverAuth certificate for the OpenVPN daemon."""
    san = _subject_alt_names(common_name, endpoint_host)
    return _issue_leaf(
        ca_cert_pem,
        ca_key_pem,
        common_name,
        extended_usage=x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.SERVER_AUTH]),
        san=san,
    )


def issue_client_cert(
    ca_cert_pem: str,
    ca_key_pem: str,
    common_name: str,
) -> tuple[str, str]:
    """Issue a clientAuth certificate for one peer."""
    return _issue_leaf(
        ca_cert_pem,
        ca_key_pem,
        common_name,
        extended_usage=x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.CLIENT_AUTH]),
        san=x509.SubjectAlternativeName([x509.DNSName(_dns_safe(common_name))]),
    )


def _issue_leaf(
    ca_cert_pem: str,
    ca_key_pem: str,
    common_name: str,
    extended_usage: x509.ExtendedKeyUsage,
    san: x509.SubjectAlternativeName,
) -> tuple[str, str]:
    ca_cert = _load_cert(ca_cert_pem)
    ca_key = _load_key(ca_key_pem)

    key = ec.generate_private_key(CURVE())
    now = _now()

    cert = (
        x509.CertificateBuilder()
        .subject_name(_name(common_name, _ca_org(ca_cert)))
        .issuer_name(ca_cert.subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - _CLOCK_SKEW)
        .not_valid_after(now + dt.timedelta(days=LEAF_VALID_DAYS))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=True,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=False,
                crl_sign=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(extended_usage, critical=False)
        .add_extension(san, critical=False)
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False
        )
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_cert.public_key()),
            critical=False,
        )
        .sign(ca_key, hashes.SHA256())
    )
    return _cert_pem(cert), _private_key_pem(key)


def _subject_alt_names(common_name: str, endpoint_host: str) -> x509.SubjectAlternativeName:
    entries: list[x509.GeneralName] = [x509.DNSName(_dns_safe(common_name))]
    host = (endpoint_host or "").strip()
    if host:
        try:
            entries.append(x509.IPAddress(ipaddress.ip_address(host)))
        except ValueError:
            if _dns_safe(host) != _dns_safe(common_name):
                entries.append(x509.DNSName(_dns_safe(host)))
    return x509.SubjectAlternativeName(entries)


def _dns_safe(value: str) -> str:
    """
    Coerce a display name into something acceptable as a DNS SAN.

    Site names are human text ("Home Server"), but a DNSName entry must look
    like a hostname or cryptography rejects it.
    """
    out = []
    for ch in value.strip().lower():
        if ch.isalnum() or ch in "-.":
            out.append(ch)
        elif ch in " _":
            out.append("-")
    cleaned = "".join(out).strip("-.")
    return cleaned or "vpn-agent"


def _ca_org(ca_cert: x509.Certificate) -> str:
    values = ca_cert.subject.get_attributes_for_oid(NameOID.ORGANIZATION_NAME)
    return values[0].value if values else "VPN Agent"


def describe_cert(cert_pem: str) -> dict:
    """Summarise a certificate for display — subject, validity, days remaining."""
    cert = _load_cert(cert_pem)
    not_after = cert.not_valid_after_utc
    remaining = (not_after - _now()).days
    common = cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
    return {
        "common_name": common[0].value if common else "",
        "not_before": cert.not_valid_before_utc.isoformat(timespec="seconds"),
        "not_after": not_after.isoformat(timespec="seconds"),
        "days_remaining": remaining,
        "expired": remaining < 0,
        "serial": f"{cert.serial_number:x}",
    }
