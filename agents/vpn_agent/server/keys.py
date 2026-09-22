"""
keys.py — WireGuard and OpenVPN key material, generated locally.

WireGuard keys are raw X25519 scalars in base64 — byte-for-byte what
`wg genkey` / `wg pubkey` produce, so nothing here depends on the wg CLI being
installed. That matters: this machine generates keys for servers that may not
have wireguard-tools yet.
"""

from __future__ import annotations

import base64
import secrets

from cryptography.hazmat.primitives.asymmetric.x25519 import (
    X25519PrivateKey,
    X25519PublicKey,
)
from cryptography.hazmat.primitives import serialization

KEY_BYTES = 32
TLS_CRYPT_BYTES = 256


def generate_wg_keypair() -> tuple[str, str]:
    """Return a fresh (private_key, public_key) pair as base64 strings."""
    private = X25519PrivateKey.generate()
    private_raw = private.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_raw = private.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return _b64(private_raw), _b64(public_raw)


def derive_wg_public(private_key_b64: str) -> str:
    """Recover the public key for an existing WireGuard private key."""
    raw = _unb64(private_key_b64, "private key")
    private = X25519PrivateKey.from_private_bytes(raw)
    public_raw = private.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return _b64(public_raw)


def generate_preshared_key() -> str:
    """
    Generate a WireGuard pre-shared key.

    This is an extra symmetric layer mixed into the handshake. It is not
    required, but it makes the tunnel resistant to an attacker who records
    traffic today and breaks X25519 with a quantum computer later.
    """
    return _b64(secrets.token_bytes(KEY_BYTES))


def validate_wg_key(key_b64: str) -> bool:
    """True if the string is a well-formed 32-byte base64 WireGuard key."""
    try:
        raw = _unb64(key_b64, "key")
    except ValueError:
        return False
    return len(raw) == KEY_BYTES


def is_valid_wg_public_key(key_b64: str) -> bool:
    """True if the string parses as an X25519 public key."""
    try:
        X25519PublicKey.from_public_bytes(_unb64(key_b64, "public key"))
    except ValueError:
        return False
    return True


def generate_tls_crypt_key() -> str:
    """
    Generate an OpenVPN tls-crypt key (static key V1 format).

    tls-crypt encrypts and authenticates the TLS control channel, so a scanner
    probing port 443 gets no OpenVPN handshake to fingerprint and unauthenticated
    packets are dropped before they reach the TLS stack. This is what makes the
    fallback endpoint quiet enough to sit on 443 next to real HTTPS.
    """
    raw = secrets.token_bytes(TLS_CRYPT_BYTES).hex()
    lines = [raw[i : i + 32] for i in range(0, len(raw), 32)]
    body = "\n".join(lines)
    return (
        "-----BEGIN OpenVPN Static key V1-----\n"
        f"{body}\n"
        "-----END OpenVPN Static key V1-----\n"
    )


def _b64(raw: bytes) -> str:
    return base64.standard_b64encode(raw).decode("ascii")


def _unb64(value: str, label: str) -> bytes:
    try:
        # validate=True rejects stray characters instead of silently skipping
        # them, so a truncated or corrupted key fails loudly here rather than
        # producing a valid-looking key of the wrong length.
        return base64.b64decode(value.strip(), validate=True)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"Malformed base64 {label}: {exc}") from exc
