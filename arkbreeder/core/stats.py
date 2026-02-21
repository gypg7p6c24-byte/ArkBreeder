from __future__ import annotations

from dataclasses import dataclass
from typing import Dict


@dataclass(frozen=True)
class StatBreakdown:
    total: float
    wild_levels: float
    tamed_levels: float
    imprinting_bonus: float
    mutations: float


def compute_wild_levels(stats: Dict[str, float]) -> Dict[str, float]:
    '''
    Placeholder for wild level computation.
    Returns zeroed values until the real formula is implemented.
    '''
    return {key: 0.0 for key in stats}
