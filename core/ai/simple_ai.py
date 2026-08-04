from __future__ import annotations

from random import Random

from core.ai.air.assessment import AirAssessmentMixin
from core.ai.air.effects import AirEffectEvaluationMixin
from core.ai.air.planning import AirPlanningMixin
from core.ai.air.reactions import AirReactionMixin
from core.ai.air.registry import get_air_card_handler
from core.ai.common import CommonAIMixin


class SimpleAI(CommonAIMixin, AirPlanningMixin, AirEffectEvaluationMixin, AirAssessmentMixin, AirReactionMixin):
    def __init__(self, rng: Random) -> None:
        self.rng = rng
        self._committed_air_plan: dict | None = None
        self._planned_rueckenwind_target_id: int | None = None
        self._planned_turbulenz_target_ids: list[int] = []
        self._planned_attacker_ids: list[int] = []

    def _get_air_card_handler(self, card):
        return get_air_card_handler(card.template.template_id)

    def _get_air_card_handler_by_template_id(self, template_id: str):
        return get_air_card_handler(template_id)

