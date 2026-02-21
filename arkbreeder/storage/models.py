from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Dict, Optional


@dataclass(frozen=True)
class Creature:
    id: Optional[int]
    external_id: Optional[str] = None
    name: str
    species: str
    sex: str
    level: int
    stats: Dict[str, float] = field(default_factory=dict)
    mutations_maternal: int = 0
    mutations_paternal: int = 0
    mother_id: Optional[int] = None
    father_id: Optional[int] = None

    def with_id(self, new_id: int) -> "Creature":
        return replace(self, id=new_id)
