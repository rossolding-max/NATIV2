"""Async CRUD repositories for the 16 domain models.

Each repository inherits ``BaseRepository[Model]`` and gets standard CRUD
with ``agency_id`` filter enforcement. The ``BrandRepository`` overrides
the filter to drop agency_id (brand is a global table per the M1 plan).
"""

from __future__ import annotations

from app.repositories.agency_profile import AgencyProfileRepository
from app.repositories.base import BaseRepository
from app.repositories.brand import BrandRepository
from app.repositories.brand_candidate import BrandCandidateRepository
from app.repositories.brand_contact import BrandContactRepository
from app.repositories.brand_deal import BrandDealRepository
from app.repositories.contract_pack import ContractPackRepository
from app.repositories.deal import DealRepository
from app.repositories.discovery_prep_pack import DiscoveryPrepPackRepository
from app.repositories.invoice_pack import InvoicePackRepository
from app.repositories.memo import MemoRepository
from app.repositories.performance_report_pack import PerformanceReportPackRepository
from app.repositories.pitch_angle import PitchAngleRepository
from app.repositories.pitch_enrollment import PitchEnrollmentRepository
from app.repositories.pitch_template import PitchTemplateRepository
from app.repositories.proposal_pack import ProposalPackRepository
from app.repositories.talent import TalentRepository

__all__ = [
    "AgencyProfileRepository",
    "BaseRepository",
    "BrandCandidateRepository",
    "BrandContactRepository",
    "BrandDealRepository",
    "BrandRepository",
    "ContractPackRepository",
    "DealRepository",
    "DiscoveryPrepPackRepository",
    "InvoicePackRepository",
    "MemoRepository",
    "PerformanceReportPackRepository",
    "PitchAngleRepository",
    "PitchEnrollmentRepository",
    "PitchTemplateRepository",
    "ProposalPackRepository",
    "TalentRepository",
]
