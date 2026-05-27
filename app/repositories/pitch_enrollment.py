"""``PitchEnrollmentRepository`` — generic CRUD for the pitch_enrollment model."""

from __future__ import annotations

from app.models.sqla.pitch_enrollment import PitchEnrollment
from app.repositories.base import BaseRepository


class PitchEnrollmentRepository(BaseRepository[PitchEnrollment]):
    model = PitchEnrollment
    pk_attr = "enrollment_id"
