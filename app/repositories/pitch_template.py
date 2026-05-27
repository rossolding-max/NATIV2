"""``PitchTemplateRepository`` — generic CRUD for the pitch_template model."""

from __future__ import annotations

from app.models.sqla.pitch_template import PitchTemplate
from app.repositories.base import BaseRepository


class PitchTemplateRepository(BaseRepository[PitchTemplate]):
    model = PitchTemplate
    pk_attr = "template_id"
