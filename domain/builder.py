from __future__ import annotations

from dataclasses import dataclass


@dataclass
class PendingBuilderCreatureBuild:
    base_aw: int = 0
    base_vw: int = 0
    base_sw: int = 0
    base_lw: int = 1
    aw: int = 0
    vw: int = 0
    sw: int = 0
    lw: int = 1
    available_resources: int = 0

    @property
    def spent_resources(self) -> int:
        return (
            max(0, self.aw - self.base_aw)
            + max(0, self.vw - self.base_vw)
            + max(0, self.sw - self.base_sw)
            + max(0, self.lw - self.base_lw)
        )
