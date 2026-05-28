"""Pick the default ``PitchTemplate`` for a given contact ``decision_role``.

Per the M9 locked-decisions:
- ``buyer``     -> buyer-direct-pitch (4 steps)
- ``influencer`` -> influencer-warm-intro (3 steps)
- ``champion``   -> champion-activation (2 steps)
- ``gatekeeper`` -> None (manual handling only — too brittle for auto-send)
- ``unknown``    -> buyer-direct-pitch (most generic default)
"""

from __future__ import annotations

from app.models.sqla.pitch_template import PitchTemplate
from app.repositories.pitch_template import PitchTemplateRepository

_FALLBACK_ROLE: str = "buyer"
_NO_AUTO_TEMPLATE: frozenset[str] = frozenset({"gatekeeper"})


async def select_template(
    decision_role: str,
    *,
    repo: PitchTemplateRepository,
) -> PitchTemplate | None:
    """Resolve the template per the M9 routing rules.

    Returns None when the role is gatekeeper (manual only) or when no
    template exists for the routing target.
    """
    role = (decision_role or "").strip().lower()
    if role in _NO_AUTO_TEMPLATE:
        return None
    if role not in {"buyer", "influencer", "champion"}:
        role = _FALLBACK_ROLE
    return await repo.find_for_decision_role(role)
