"""Sentry breadcrumb helper for vendor calls.

Lives in ``app/observability/`` rather than ``app/vendors/`` so the vendor
package has no dependency on the observability module's import side effects.
"""

from __future__ import annotations

from typing import Any

import sentry_sdk


def vendor_breadcrumb(
    vendor: str,
    endpoint: str,
    status: int | str | None = None,
    **extra: Any,
) -> None:
    """Drop a Sentry breadcrumb for a vendor HTTP call.

    Called from ``BaseVendorClient`` before and after each request. Cheap when
    Sentry is uninitialised — ``sentry_sdk.add_breadcrumb`` is a no-op then.
    """
    data: dict[str, Any] = {"endpoint": endpoint}
    if status is not None:
        data["status"] = status
    data.update(extra)
    sentry_sdk.add_breadcrumb(
        category="vendor",
        message=f"{vendor}.{endpoint}",
        level="info",
        data=data,
    )
