from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MutationSummary:
    maternal: int
    paternal: int


def total_mutations(summary: MutationSummary) -> int:
    return summary.maternal + summary.paternal
