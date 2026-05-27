"""Step 1 — seed profile creator.

Captures the minimum required data to write the first talent row:
``id`` (kebab-case slug), ``name``, optional ``location.country`` (drives
timezone + disclosure-defaults), and the FIRST platform handle (so the
Step 2 OAuth flow has something to attach to).

Country → timezone + disclosure defaults are looked up via a small inline
table; v0.2 can replace with a proper i18n lookup.
"""

from __future__ import annotations

import re
from typing import Any

from app.errors import ConflictError, ValidationError
from app.models.sqla.talent import Talent
from app.repositories.talent import TalentRepository

# Minimal country → (timezone, disclosure-style) seeds. Per the workflow
# doc: most agencies disclose via ``#ad`` regardless of country; the field
# exists so v0.2 can specialise (e.g. ``#advertising`` in IT, ``#anzeige``
# in DE, etc).
_COUNTRY_DEFAULTS: dict[str, tuple[str, str]] = {
    "US": ("America/Los_Angeles", "#ad"),
    "GB": ("Europe/London", "#ad"),
    "UK": ("Europe/London", "#ad"),
    "CA": ("America/Toronto", "#ad"),
    "AU": ("Australia/Sydney", "#ad"),
    "DE": ("Europe/Berlin", "#anzeige"),
    "FR": ("Europe/Paris", "#ad"),
    "IE": ("Europe/Dublin", "#ad"),
    "NZ": ("Pacific/Auckland", "#ad"),
}

_SLUG_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]*$")


def derive_slug(name: str) -> str:
    """Lower-case + hyphenate ``name`` into a kebab-case talent_id."""
    candidate = name.lower().strip()
    candidate = re.sub(r"[^a-z0-9]+", "-", candidate)
    candidate = candidate.strip("-")
    if not candidate or not _SLUG_PATTERN.match(candidate):
        raise ValidationError(
            f"could not derive a valid slug from name {name!r}",
            field="name",
        )
    return candidate


def defaults_for_country(country_code: str | None) -> dict[str, str]:
    """Return ``timezone`` + ``disclosure_style`` defaults for a country.

    Falls back to UTC + ``#ad`` when the country is unknown or absent.
    """
    if country_code:
        upper = country_code.upper()
        if upper in _COUNTRY_DEFAULTS:
            tz, disclosure = _COUNTRY_DEFAULTS[upper]
            return {"timezone": tz, "disclosure_style": disclosure}
    return {"timezone": "UTC", "disclosure_style": "#ad"}


class TalentSeedService:
    """Step 1 — create the talent draft row + apply country defaults."""

    def __init__(self, repo: TalentRepository) -> None:
        self._repo = repo

    async def create_seed(
        self,
        *,
        name: str,
        slug: str | None = None,
        country: str | None = None,
        timezone: str | None = None,
        initial_platform: dict[str, str] | None = None,
        content_niches: list[str] | None = None,
        agency_id: Any = None,
    ) -> Talent:
        """Insert a new ``talent`` row with the Step-1 fields populated."""
        talent_id = (slug or derive_slug(name)).strip().lower()
        if not _SLUG_PATTERN.match(talent_id):
            raise ValidationError(
                "talent slug must match ^[a-z0-9][a-z0-9-]*$",
                field="slug",
                detail={"received": talent_id},
            )

        existing = await self._repo.get_by_talent_id(talent_id)
        if existing is not None:
            raise ConflictError(
                f"talent {talent_id!r} already exists",
                detail={"talent_id": talent_id},
            )

        defaults = defaults_for_country(country)
        data: dict[str, Any] = {
            "id": talent_id,
            "name": name,
            "timezone": timezone or defaults["timezone"],
            "disclosure_defaults": {"style": defaults["disclosure_style"]},
            "platforms": [initial_platform] if initial_platform else [],
            "content_niches": content_niches or [],
        }
        if country:
            data["location"] = {"country": country.upper()}

        instance = Talent(
            talent_id=talent_id,
            name=name,
            status="onboarding",
            data=data,
        )
        if agency_id is not None:
            instance.agency_id = agency_id
        return await self._repo.create(instance)
