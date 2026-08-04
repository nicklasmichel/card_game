from __future__ import annotations

from core.models import CardInstance, PHASE_SUMMONING


class AIScenarioBuilder:
    def __init__(self, case) -> None:
        self.case = case
        self.engine = case.engine
        self.engine.active_player_index = self.engine.ai_player.player_id

    def phase(self, phase: str):
        self.engine.phase = phase
        return self

    def ai_hand(self, *template_ids: str):
        self.engine.ai_player.hand = [
            CardInstance(self.engine.make_instance_id(), self.engine.templates[template_id])
            for template_id in template_ids
        ]
        return self

    def ai_resources(self, *template_ids: str):
        self.engine.ai_player.resources = [self.case.make_resource(template_id) for template_id in template_ids]
        return self

    def human_life(self, life: int):
        self.engine.human_player.life = life
        return self

    def ai_deaths_this_turn(self, deaths: int):
        self.engine.creatures_died_this_turn = deaths
        return self

    def build(self):
        if not self.engine.phase:
            self.engine.phase = PHASE_SUMMONING
        return self.engine
