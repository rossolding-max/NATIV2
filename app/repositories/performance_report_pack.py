"""``PerformanceReportPackRepository`` — generic CRUD for the performance_report_pack model."""

from __future__ import annotations

from app.models.sqla.performance_report_pack import PerformanceReportPack
from app.repositories.base import BaseRepository


class PerformanceReportPackRepository(BaseRepository[PerformanceReportPack]):
    model = PerformanceReportPack
    pk_attr = "performance_report_pack_id"
