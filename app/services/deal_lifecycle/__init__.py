"""Phase 4 — Deal lifecycle skeleton.

Enforces the 6-stage by 28-substage state machine per
``docs/deal_lifecycle_workflow.md``. Owns:

- ``transitions`` — static TRANSITIONS map + TERMINAL_SUBSTAGES + AUTO_ADVANCE rules.
- ``state_machine`` — validates one transition; emits a chain (1-2 steps)
  when the target substage triggers an auto-cross-stage advance.
- ``loss_reasons`` — Reason enum re-export + lost_at_stage helper.
- ``orchestrator`` — applies a transition end-to-end (chain + audit log
  + scalar column sync); also exposes ``record_loss``.

M11-M15 plug into this scaffold for per-stage pack generation; M10
itself ships no LLM calls.
"""

from app.services.deal_lifecycle import (
    loss_reasons,
    orchestrator,
    state_machine,
    transitions,
)

__all__ = ["loss_reasons", "orchestrator", "state_machine", "transitions"]
