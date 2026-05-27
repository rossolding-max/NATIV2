"""SPF / DKIM / DMARC verification via direct DNS lookups.

Smartlead does NOT expose a DNS-verification API (confirmed against
``https://helpcenter.smartlead.ai/en/articles/125-full-api-documentation``).
So Phase 0 verifies the agency has set up SPF/DKIM/DMARC by querying their
TXT records directly using ``dnspython`` (already pulled in transitively
via ``email-validator``).

Workflow:
1. Agency follows Smartlead's UI walkthrough to add the records to their DNS.
2. Phase 0 setup endpoint calls ``check_all(domain, dkim_selector)`` to
   confirm propagation.
3. Result is persisted into ``agency_profile.data.sending_mailboxes[0]``.

DNS lookups are async via ``dns.asyncresolver``. Default timeout 5s.
"""

from __future__ import annotations

from dataclasses import dataclass

import dns.asyncresolver
import dns.exception
import dns.rdatatype
import dns.resolver

_DEFAULT_TIMEOUT_SECONDS = 5.0
_DEFAULT_LIFETIME_SECONDS = 10.0
_DEFAULT_DKIM_SELECTOR = "smartlead"


@dataclass(frozen=True)
class DnsRecordCheck:
    """Single-record check outcome."""

    record_type: str
    queried_name: str
    found: bool
    value: str | None
    error: str | None = None


@dataclass(frozen=True)
class DnsCheckResult:
    """Aggregate of SPF + DKIM + DMARC checks for one domain."""

    domain: str
    dkim_selector: str
    spf: DnsRecordCheck
    dkim: DnsRecordCheck
    dmarc: DnsRecordCheck

    @property
    def all_verified(self) -> bool:
        return self.spf.found and self.dkim.found and self.dmarc.found


def _build_resolver(
    timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
    lifetime_seconds: float = _DEFAULT_LIFETIME_SECONDS,
) -> dns.asyncresolver.Resolver:
    resolver = dns.asyncresolver.Resolver()
    resolver.timeout = timeout_seconds
    resolver.lifetime = lifetime_seconds
    return resolver


async def _lookup_txt(
    name: str, resolver: dns.asyncresolver.Resolver
) -> tuple[bool, str | None, str | None]:
    """Return (found, joined_value, error_str). Joins multi-string TXT records."""
    try:
        answer = await resolver.resolve(name, dns.rdatatype.TXT)
    except dns.resolver.NXDOMAIN:
        return False, None, "nxdomain"
    except dns.resolver.NoAnswer:
        return False, None, "no_txt_record"
    except dns.exception.Timeout:
        return False, None, "timeout"
    except dns.exception.DNSException as exc:
        return False, None, f"dns_error:{type(exc).__name__}"

    for rrset in answer:
        # Each rrset has .strings — a tuple of bytes that are concatenated.
        joined = b"".join(rrset.strings).decode("utf-8", errors="replace")
        return True, joined, None
    return False, None, "empty_rrset"


async def check_spf(
    domain: str, *, resolver: dns.asyncresolver.Resolver | None = None
) -> DnsRecordCheck:
    """Look up the SPF TXT record on ``domain`` itself."""
    resolver = resolver or _build_resolver()
    found, value, error = await _lookup_txt(domain, resolver)
    # An SPF record begins with ``v=spf1``. A TXT record at the apex
    # without that prefix is not an SPF record (could be Google site verify).
    is_spf = found and value is not None and value.lower().startswith("v=spf1")
    return DnsRecordCheck(
        record_type="SPF",
        queried_name=domain,
        found=is_spf,
        value=value if is_spf else None,
        error=error if not is_spf else None,
    )


async def check_dkim(
    domain: str,
    *,
    selector: str = _DEFAULT_DKIM_SELECTOR,
    resolver: dns.asyncresolver.Resolver | None = None,
) -> DnsRecordCheck:
    """Look up the DKIM TXT record at ``{selector}._domainkey.{domain}``.

    Smartlead's default DKIM selector is ``smartlead`` but agencies may
    override during their Smartlead UI setup. Caller passes the selector.
    """
    resolver = resolver or _build_resolver()
    queried = f"{selector}._domainkey.{domain}"
    found, value, error = await _lookup_txt(queried, resolver)
    # A DKIM record begins with ``v=DKIM1``.
    is_dkim = found and value is not None and "v=dkim1" in value.lower()
    return DnsRecordCheck(
        record_type="DKIM",
        queried_name=queried,
        found=is_dkim,
        value=value if is_dkim else None,
        error=error if not is_dkim else None,
    )


async def check_dmarc(
    domain: str, *, resolver: dns.asyncresolver.Resolver | None = None
) -> DnsRecordCheck:
    """Look up the DMARC TXT record at ``_dmarc.{domain}``."""
    resolver = resolver or _build_resolver()
    queried = f"_dmarc.{domain}"
    found, value, error = await _lookup_txt(queried, resolver)
    is_dmarc = found and value is not None and value.lower().startswith("v=dmarc1")
    return DnsRecordCheck(
        record_type="DMARC",
        queried_name=queried,
        found=is_dmarc,
        value=value if is_dmarc else None,
        error=error if not is_dmarc else None,
    )


async def check_all(
    domain: str,
    *,
    dkim_selector: str = _DEFAULT_DKIM_SELECTOR,
    resolver: dns.asyncresolver.Resolver | None = None,
) -> DnsCheckResult:
    """Run SPF + DKIM + DMARC checks against a domain."""
    resolver = resolver or _build_resolver()
    spf = await check_spf(domain, resolver=resolver)
    dkim = await check_dkim(domain, selector=dkim_selector, resolver=resolver)
    dmarc = await check_dmarc(domain, resolver=resolver)
    return DnsCheckResult(
        domain=domain,
        dkim_selector=dkim_selector,
        spf=spf,
        dkim=dkim,
        dmarc=dmarc,
    )
