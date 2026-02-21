from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class ParentLinks:
    mother_id: Optional[int]
    father_id: Optional[int]


def validate_pedigree(links: ParentLinks) -> None:
    '''
    Placeholder validation for pedigree relationships.
    '''
    if links.mother_id is None and links.father_id is None:
        return
