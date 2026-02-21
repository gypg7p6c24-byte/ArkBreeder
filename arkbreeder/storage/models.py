from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Dict, Optional


@dataclass(frozen=True)
class Creature:
    id: Optional[int]
    name: str
    species: str
    sex: str
    level: int
    external_id: Optional[str] = None
    stats: Dict[str, float] = field(default_factory=dict)
    mutations_maternal: int = 0
    mutations_paternal: int = 0
    mother_id: Optional[int] = None
    father_id: Optional[int] = None
    mother_external_id: Optional[str] = None
    father_external_id: Optional[str] = None
    updated_at: Optional[str] = None

    def with_id(self, new_id: int) -> "Creature":
        return replace(self, id=new_id)
