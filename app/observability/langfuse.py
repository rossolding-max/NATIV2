"""Langfuse initialisation. See ``docs/architecture.md`` § 7.

M0 provides only the init surface — per-call instrumentation lands in M2
when the first agent invocation appears.

No-op if ``LANGFUSE_ENABLED == False`` or the keys are unset.
"""

from __future__ import annotations

from typing import Any

from app.config import settings

_client: Any | None = None


def init_langfuse() -> None:
    """Instantiate the Langfuse client. Idempotent."""
    global _client

    if not settings.langfuse_enabled:
        return
    if settings.langfuse_public_key is None or settings.langfuse_secret_key is None:
        # Configured to enable but no keys -- noop with a warning in logs handled
        # by the caller. We avoid raising here so /health still boots in M0.
        return

    # Import lazily so the dep can be absent in M0 test envs without keys.
    from langfuse import Langfuse  # type: ignore[import-not-found]

    _client = Langfuse(
        public_key=settings.langfuse_public_key.get_secret_value(),
        secret_key=settings.langfuse_secret_key.get_secret_value(),
        host=str(settings.langfuse_host),
    )


def get_client() -> Any | None:
    """Return the Langfuse client, or ``None`` if uninitialised / disabled."""
    return _client
