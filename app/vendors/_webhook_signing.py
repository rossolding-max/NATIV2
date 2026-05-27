"""HMAC-SHA256 signature verification for vendor webhooks.

Both Smartlead (``X-Smartlead-Signature``) and Meta (``X-Hub-Signature-256``,
prefixed with ``sha256=``) use HMAC-SHA256 of the raw request body. This
helper handles both formats; M3 consumes it in ``smartlead.py`` and
``meta_graph.py``.

Always uses ``hmac.compare_digest`` to avoid timing attacks.
"""

from __future__ import annotations

import hashlib
import hmac


def verify_hmac_sha256(
    raw_body: bytes,
    signature_header: str | None,
    secret: str,
    *,
    algorithm_prefix: str | None = None,
) -> bool:
    """Return True if ``signature_header`` matches HMAC-SHA256(raw_body, secret).

    Args:
        raw_body: The exact bytes of the request body. The caller MUST
            capture the body BEFORE FastAPI parses it as JSON.
        signature_header: The header value from the vendor. ``None`` returns
            ``False`` (missing signature = rejected).
        secret: The webhook signing secret (``smartlead_webhook_secret`` or
            ``meta_app_secret``).
        algorithm_prefix: For Meta, pass ``"sha256="`` — the prefix is stripped
            before compare. Smartlead sends the bare hex digest, so pass ``None``.

    Returns:
        True iff the signature is well-formed AND matches.
    """
    if not signature_header:
        return False

    candidate = signature_header
    if algorithm_prefix is not None:
        if not candidate.startswith(algorithm_prefix):
            return False
        candidate = candidate[len(algorithm_prefix) :]

    expected = hmac.new(
        secret.encode("utf-8"),
        raw_body,
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(expected, candidate)
