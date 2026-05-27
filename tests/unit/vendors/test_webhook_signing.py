"""Unit tests for ``app.vendors._webhook_signing``."""

from __future__ import annotations

import hashlib
import hmac

from app.vendors._webhook_signing import verify_hmac_sha256


def _sign(body: bytes, secret: str) -> str:
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def test_unit__smartlead_format__valid_signature__returns_true() -> None:
    body = b'{"event":"opened"}'
    secret = "smartlead-secret-1"
    sig = _sign(body, secret)
    assert verify_hmac_sha256(body, sig, secret) is True


def test_unit__smartlead_format__tampered_body__returns_false() -> None:
    secret = "smartlead-secret-1"
    sig = _sign(b'{"event":"opened"}', secret)
    assert verify_hmac_sha256(b'{"event":"clicked"}', sig, secret) is False


def test_unit__meta_format__valid_signature_with_sha256_prefix__returns_true() -> None:
    body = b'{"object":"instagram"}'
    secret = "meta-app-secret"
    sig = "sha256=" + _sign(body, secret)
    assert verify_hmac_sha256(body, sig, secret, algorithm_prefix="sha256=") is True


def test_unit__meta_format__missing_prefix__returns_false() -> None:
    body = b'{"object":"instagram"}'
    secret = "meta-app-secret"
    sig = _sign(body, secret)
    # Without the prefix, verification with the prefix arg MUST fail.
    assert verify_hmac_sha256(body, sig, secret, algorithm_prefix="sha256=") is False


def test_unit__missing_header__returns_false() -> None:
    assert verify_hmac_sha256(b"body", None, "secret") is False


def test_unit__wrong_secret__returns_false() -> None:
    body = b"payload"
    sig = _sign(body, "correct-secret")
    assert verify_hmac_sha256(body, sig, "wrong-secret") is False
