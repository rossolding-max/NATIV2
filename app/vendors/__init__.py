"""Vendor wrappers — one typed async client per external service.

Anthropic stays at ``app/agents/llm_client.py`` (M2 location) by design;
see ``docs/architecture.md`` § 10. All other vendors live here.

Imports are deferred — accessing a vendor client requires the corresponding
secret in settings. Module-level imports of clients that need missing keys
would crash app startup; the per-module ``__init__`` raises ``IntegrationError``
on construction instead.
"""

from app.vendors.smartlead import SmartleadClient

__all__ = ["SmartleadClient"]
