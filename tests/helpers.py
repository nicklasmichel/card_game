from __future__ import annotations

import unittest

from core.game_logic import GameEngine
from core.models import BattlefieldCreature, CardInstance, CombatUnitSnapshot, PlayerState, ResourceCard


class EngineTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = GameEngine()
        self.engine.players = [
            PlayerState(0, "Spieler", True),
            PlayerState(1, "Gegner", False),
        ]
        self.engine.active_player_index = 0
        self.engine.reset_combat_state()
        self.engine.log_messages.clear()

    def make_creature(self, template_id: str, owner_id: int, ready: bool = True) -> BattlefieldCreature:
        template = self.engine.templates[template_id]
        creature = BattlefieldCreature.from_card(CardInstance(self.engine.make_instance_id(), template))
        if ready:
            creature.tapped = False
            creature.summoning_sick = False
        self.engine.players[owner_id].battlefield.append(creature)
        return creature

    def make_resource(self, template_id: str) -> ResourceCard:
        card = CardInstance(self.engine.make_instance_id(), self.engine.templates[template_id])
        return ResourceCard(template=card.template, resource_id=card.instance_id)

    def snapshot(self, creature: BattlefieldCreature) -> CombatUnitSnapshot:
        return CombatUnitSnapshot(
            unit_id=creature.unit_id,
            template_id=getattr(creature, "template_id", None),
            name=creature.name,
            cost=creature.cost,
            aw=creature.aw,
            vw=creature.vw,
            lw=creature.lw,
            sw=creature.sw,
            current_hp=creature.current_hp,
            element=creature.element,
            abilities=creature.abilities,
            rules_text=getattr(creature, "rules_text", ""),
            tapped=creature.tapped,
        )
