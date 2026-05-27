"""``BaseVendorClient`` — shared HTTP request mechanics for all vendor wrappers.

Every vendor client inherits from this. It handles:

- Issuing the request via the shared ``httpx.AsyncClient`` singleton.
- Dropping a Sentry breadcrumb before each call.
- Emitting a structlog ``vendor_call`` event with vendor + endpoint + status
  + latency (no PII; api keys redacted by the structlog processor).
- Mapping vendor-level failures into the ``IntegrationError`` hierarchy:
  - Connect/read timeout → ``IntegrationTimeoutError``.
  - HTTP 429 → ``IntegrationRateLimitError`` (with ``Retry-After`` in detail).
  - HTTP 4xx / 5xx → ``IntegrationError`` with status in detail.

Authentication and per-vendor URL conventions are left to subclasses — this
base class is unopinionated about how a request is authenticated.
"""

from __future__ import annotations

import time
from typing import Any

import httpx

from app.errors import IntegrationError, IntegrationRateLimitError, IntegrationTimeoutError
from app.observability.vendor import vendor_breadcrumb
from app.utils.logging import get_logger
from app.vendors._http_client import get_async_http_client

log = get_logger(__name__)


class BaseVendorClient:
    """Common request orchestration for vendor wrappers.

    Subclasses set ``vendor_name`` (used in logs + breadcrumbs + rate-limit
    keys) and implement vendor-specific methods that ultimately call
    :meth:`_request`.
    """

    vendor_name: str = "unknown"

    async def _request(
        self,
        method: str,
        url: str,
        *,
        endpoint: str,
        params: dict[str, Any] | None = None,
        json: Any = None,
        data: Any = None,
        headers: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> httpx.Response:
        """Issue an HTTP request and apply the vendor-error mapping.

        ``endpoint`` is a stable identifier used in logs + breadcrumbs (e.g.
        ``"create_campaign"`` not the full URL with IDs). It is not a PII risk
        because it's derived from method names, not user data.
        """
        client = get_async_http_client()
        vendor_breadcrumb(self.vendor_name, endpoint)
        start = time.monotonic()
        try:
            response = await client.request(
                method,
                url,
                params=params,
                json=json,
                data=data,
                headers=headers,
                timeout=timeout,
            )
        except (httpx.ConnectTimeout, httpx.ReadTimeout, httpx.WriteTimeout) as exc:
            latency_ms = int((time.monotonic() - start) * 1000)
            log.warning(
                "vendor_timeout",
                vendor=self.vendor_name,
                endpoint=endpoint,
                latency_ms=latency_ms,
            )
            raise IntegrationTimeoutError(
                f"{self.vendor_name} {endpoint} timed out",
                detail={"vendor": self.vendor_name, "endpoint": endpoint},
            ) from exc

        latency_ms = int((time.monotonic() - start) * 1000)
        log.info(
            "vendor_call",
            vendor=self.vendor_name,
            endpoint=endpoint,
            status=response.status_code,
            latency_ms=latency_ms,
        )
        vendor_breadcrumb(
            self.vendor_name, endpoint, status=response.status_code, latency_ms=latency_ms
        )

        if response.status_code == 429:
            retry_after = self._parse_retry_after(response)
            raise IntegrationRateLimitError(
                f"{self.vendor_name} {endpoint} rate-limited",
                detail={
                    "vendor": self.vendor_name,
                    "endpoint": endpoint,
                    "status": 429,
                    "retry_after_seconds": retry_after,
                },
            )
        if response.status_code >= 400:
            raise IntegrationError(
                f"{self.vendor_name} {endpoint} returned {response.status_code}",
                detail={
                    "vendor": self.vendor_name,
                    "endpoint": endpoint,
                    "status": response.status_code,
                    "body": self._safe_body_excerpt(response),
                },
            )
        return response

    @staticmethod
    def _parse_retry_after(response: httpx.Response) -> float | None:
        """Read the ``Retry-After`` header as seconds (numeric form only).

        Vendors may also send an HTTP-date form; v0.1 only handles the simple
        numeric case — extending later if a vendor needs the date form.
        """
        raw = response.headers.get("Retry-After")
        if raw is None:
            return None
        try:
            return float(raw)
        except ValueError:
            return None

    @staticmethod
    def _safe_body_excerpt(response: httpx.Response) -> str:
        """First 256 chars of the response body for log diagnostics.

        Truncated so log lines don't blow up. Body is logged for non-2xx
        responses only; no PII expected from vendor error envelopes.
        """
        try:
            return response.text[:256]
        except Exception:
            return ""
