"""Hand-written SQLAlchemy 2 async ORM models for the 16 domain schemas.

Imports below are required so Alembic's autogenerate picks up the metadata
when Base.metadata is queried.

Reference data tables (industry, niche, etc.) are NOT modelled here —
those taxonomies live in ``app.utils.taxonomies`` as in-memory dicts per
the M1 plan locked decision.
"""

from __future__ import annotations

from app.models.sqla.agency_profile import AgencyProfile
from app.models.sqla.brand import Brand
from app.models.sqla.brand_candidate import BrandCandidate
from app.models.sqla.brand_contact import BrandContact
from app.models.sqla.brand_deal import BrandDeal
from app.models.sqla.contract_pack import ContractPack
from app.models.sqla.deal import Deal
from app.models.sqla.discovery_prep_pack import DiscoveryPrepPack
from app.models.sqla.invoice_pack import InvoicePack
from app.models.sqla.memo import Memo
from app.models.sqla.performance_report_pack import PerformanceReportPack
from app.models.sqla.pitch_angle import PitchAngle
from app.models.sqla.pitch_enrollment import PitchEnrollment
from app.models.sqla.pitch_template import PitchTemplate
from app.models.sqla.proposal_pack import ProposalPack
from app.models.sqla.talent import Talent
from app.models.sqla.talent_vault import TalentVault

__all__ = [
    "AgencyProfile",
    "Brand",
    "BrandCandidate",
    "BrandContact",
    "BrandDeal",
    "ContractPack",
    "Deal",
    "DiscoveryPrepPack",
    "InvoicePack",
    "Memo",
    "PerformanceReportPack",
    "PitchAngle",
    "PitchEnrollment",
    "PitchTemplate",
    "ProposalPack",
    "Talent",
    "TalentVault",
]
