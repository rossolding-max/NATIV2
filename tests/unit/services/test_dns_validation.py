"""Unit tests for ``app.services.dns_validation``.

DNS lookups are mocked via patching ``dns.asyncresolver.Resolver.resolve``.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import dns.exception
import dns.resolver

from app.services.dns_validation import check_all, check_dkim, check_dmarc, check_spf


def _fake_answer(txt_value: str) -> Any:
    """Build the minimal dnspython answer shape that yields one TXT rdata."""
    rrset = MagicMock()
    rrset.strings = (txt_value.encode("utf-8"),)
    answer = [rrset]
    return answer


def _make_resolver_with(response: Any) -> Any:
    """Return a real Resolver instance with .resolve patched as AsyncMock."""
    from app.services import dns_validation as dnsv

    resolver = dnsv._build_resolver()  # pyright: ignore[reportPrivateUsage]
    if isinstance(response, Exception):
        resolver.resolve = AsyncMock(side_effect=response)  # type: ignore[method-assign]
    else:
        resolver.resolve = AsyncMock(return_value=response)  # type: ignore[method-assign]
    return resolver


async def test_unit__check_spf__valid_record__found_true() -> None:
    resolver = _make_resolver_with(_fake_answer("v=spf1 include:_spf.smartlead.ai ~all"))
    result = await check_spf("acme.com", resolver=resolver)
    assert result.found is True
    assert result.value is not None
    assert "spf1" in result.value


async def test_unit__check_spf__non_spf_txt__found_false() -> None:
    # An apex TXT record that isn't SPF (e.g. Google site verify) should not match.
    resolver = _make_resolver_with(_fake_answer("google-site-verification=abc"))
    result = await check_spf("acme.com", resolver=resolver)
    assert result.found is False
    assert result.value is None


async def test_unit__check_dkim__custom_selector__found_true() -> None:
    resolver = _make_resolver_with(_fake_answer("v=DKIM1; k=rsa; p=MIIBI..."))
    result = await check_dkim("acme.com", selector="s2", resolver=resolver)
    assert result.found is True
    assert result.queried_name == "s2._domainkey.acme.com"


async def test_unit__check_dmarc__valid_record__found_true() -> None:
    resolver = _make_resolver_with(
        _fake_answer("v=DMARC1; p=quarantine; rua=mailto:dmarc@acme.com")
    )
    result = await check_dmarc("acme.com", resolver=resolver)
    assert result.found is True
    assert result.queried_name == "_dmarc.acme.com"


async def test_unit__check_all__aggregates_three_records() -> None:
    """Each check uses the same resolver, but the resolve mock returns different
    values based on the queried name."""

    async def _resolve(name: Any, _rdtype: Any) -> Any:
        name_str = str(name)
        if name_str == "acme.com":
            return _fake_answer("v=spf1 ~all")
        if name_str == "smartlead._domainkey.acme.com":
            return _fake_answer("v=DKIM1; p=...")
        if name_str == "_dmarc.acme.com":
            return _fake_answer("v=DMARC1; p=none")
        raise dns.resolver.NXDOMAIN()

    from app.services import dns_validation as dnsv

    resolver = dnsv._build_resolver()  # pyright: ignore[reportPrivateUsage]
    resolver.resolve = AsyncMock(side_effect=_resolve)  # type: ignore[method-assign]

    result = await check_all("acme.com", resolver=resolver)
    assert result.all_verified is True


async def test_unit__check_spf__nxdomain__returns_not_found() -> None:
    resolver = _make_resolver_with(dns.resolver.NXDOMAIN())
    result = await check_spf("missing-domain.example", resolver=resolver)
    assert result.found is False
    assert result.error == "nxdomain"


async def test_unit__check_dmarc__timeout__returns_timeout_error() -> None:
    resolver = _make_resolver_with(dns.exception.Timeout())
    result = await check_dmarc("acme.com", resolver=resolver)
    assert result.found is False
    assert result.error == "timeout"


async def test_unit__check_dkim__no_answer__returns_no_txt_record() -> None:
    # The resolver raises NoAnswer (record doesn't exist at this name).
    # Patch __init__ to bypass dnspython's required-kwarg validation.
    with patch.object(dns.resolver.NoAnswer, "__init__", lambda *a, **k: None):  # type: ignore[misc]
        resolver = _make_resolver_with(dns.resolver.NoAnswer(response=MagicMock()))
        result = await check_dkim("acme.com", resolver=resolver)
        assert result.found is False
        assert result.error == "no_txt_record"
