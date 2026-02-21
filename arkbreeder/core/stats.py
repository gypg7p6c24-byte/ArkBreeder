from __future__ import annotations

from dataclasses import dataclass
from typing import Dict


@dataclass(frozen=True)
class StatBreakdown:
    total: int
    wild_levels: int
    tamed_levels: int
    imprinting_bonus: int
    mutations: int


def compute_wild_levels(stats: Dict[str, int]) -> Dict[str, int]:
    '''
    Placeholder for wild level computation.
    Returns zeroed values until the real formula is implemented.
    '''
    return {key: 0 for key in stats}
