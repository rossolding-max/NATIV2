"""Factory stub for memo.

M0 baseline: emits raw dict instances. M1 swaps Meta.model to the
generated Pydantic class and fills in field generators.
"""

from __future__ import annotations

import factory


class MemoFactory(factory.DictFactory):
    """Placeholder factory; M1 replaces the model."""
