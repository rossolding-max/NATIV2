"""``PitchAngleRepository`` — generic CRUD for the pitch_angle model."""

from __future__ import annotations

from app.models.sqla.pitch_angle import PitchAngle
from app.repositories.base import BaseRepository


class PitchAngleRepository(BaseRepository[PitchAngle]):
    model = PitchAngle
    pk_attr = "angle_id"
