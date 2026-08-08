from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .enums import Ability, CardType, Element, ReactionTrigger, SpellEffect, SpellTargetMode, SpellTiming


@dataclass(frozen=True)
class CardCost:
    resources: int = 0
    recycle: int = 0

    def __post_init__(self) -> None:
        if self.resources < 0:
            raise ValueError("Ressourcenkosten duerfen nicht negativ sein.")
        if self.recycle < 0:
            raise ValueError("Recyclekosten duerfen nicht negativ sein.")

    @property
    def total_value(self) -> int:
        return self.resources + self.recycle


@dataclass(frozen=True)
class CardTemplate:
    template_id: str
    name: str
    cost: CardCost
    aw: int
    vw: int
    element: Element
    lw: int | None = None
    sw: int | None = None
    abilities: frozenset[Ability] = frozenset()
    card_type: CardType = CardType.CREATURE
    rules_text: str = ""
    self_damage_on_play: int = 0
    opponent_damage_on_play: int = 0
    discard_self_on_play: int = 0
    discard_opponent_on_play: int = 0
    reveal_opponent_hand: bool = False
    return_to_deck_end_of_turn: bool = False
    cannot_block: bool = False
    must_attack_each_turn: bool = False
    all_attackers_die_bonus: int = 0
    spell_effect: SpellEffect | None = None
    spell_timing: SpellTiming | None = None
    legal_reaction_windows: tuple[ReactionTrigger, ...] = ()
    reaction_trigger: ReactionTrigger | None = None
    target_mode: SpellTargetMode = SpellTargetMode.NONE
    spell_amount: int = 0
    combat_aw_bonus: int = 0
    combat_sw_bonus: int = 0
    spell_draw_count: int = 0
    sacrifice_own_creature_on_cast: bool = False
    draw_on_play: int = 0
    draw_on_attack: int = 0
    draw_on_death: int = 0
    draw_on_player_damage: int = 0
    tap_enemy_creature_on_play: int = 0
    return_other_own_haste_on_combat_death: bool = False
    own_flying_attack_aura: int = 0

    def __post_init__(self) -> None:
        if self.card_type == CardType.CREATURE:
            if self.aw <= 0 or self.vw < 0:
                raise ValueError(f"{self.template_id} muss positiven AW und nichtnegativen VW besitzen.")
            if self.element in {Element.AIR, Element.FIRE, Element.EARTH} and (self.lw is None or self.sw is None):
                raise ValueError(f"{self.template_id} muss explizite LW- und SW-Werte besitzen.")
            if self.effective_lw <= 0 or self.effective_sw <= 0:
                raise ValueError(f"{self.template_id} muss positive LW- und SW-Werte besitzen.")
            return
        if self.lw is not None or self.sw is not None:
            raise ValueError(f"{self.template_id} ist keine Kreatur und darf keine LW-/SW-Werte besitzen.")

    def has_ability(self, ability) -> bool:
        return ability in self.abilities

    @property
    def resource_cost(self) -> int:
        return self.cost.resources

    @property
    def recycle_cost(self) -> int:
        return self.cost.recycle

    @property
    def effective_lw(self) -> int:
        # Temporary migration fallback for not-yet-migrated creature cards.
        return self.vw if self.lw is None else self.lw

    @property
    def effective_sw(self) -> int:
        # Temporary migration fallback for not-yet-migrated creature cards.
        return self.aw if self.sw is None else self.sw


@dataclass
class CardInstance:
    instance_id: int
    template: CardTemplate
    was_recycled: bool = False


@dataclass
class ResourceCard:
    template: CardTemplate
    resource_id: int | None = None
    tapped: bool = False


@dataclass
class PendingRecyclePayment:
    card_instance_id: int
    required_count: int
    selected_resource_ids: list[int]
    return_phase: str


@dataclass
class PendingForcedDiscard:
    target_player_id: int
    required_count: int
    selected_card_ids: list[int]
    source_card_name: str
    return_phase: str


@dataclass(frozen=True)
class SpellTargetRef:
    target_type: str
    player_id: int | None = None
    creature_id: int | None = None
    card_instance_id: int | None = None
    die_index: int | None = None
    die_role: str | None = None
    open_die_id: int | None = None


@dataclass
class ReactionContext:
    trigger: ReactionTrigger
    active_player: Any
    source_player: Any | None = None
    source_card: CardInstance | None = None
    source_creature: Any | None = None
    target_creature: Any | None = None
    opposing_creature: Any | None = None
    die_result: int | None = None
    damage_amount: int | None = None
    attacker_die: Any | None = None
    blocker_die: Any | None = None
    attacker_creature: Any | None = None
    blocker_creature: Any | None = None
    pending_damage_attacker_id: int | None = None


@dataclass
class StackItem:
    source_card: CardInstance
    controller: Any
    targets: list[SpellTargetRef]
    effect: SpellEffect
    context: ReactionContext | None
    amount: int = 0
    draw_count: int = 0
    sacrificed_creature_power: int = 0
    selected_keyword_ability: Ability | None = None
    selected_combat_bonus_mode: str | None = None


@dataclass
class PendingSpellCast:
    card_instance_id: int
    controller_id: int
    origin_phase: str
    selected_targets: list[SpellTargetRef] = field(default_factory=list)
    selected_sacrifice_creature_id: int | None = None
    selected_keyword_ability: Ability | None = None
    selected_combat_bonus_mode: str | None = None
    selected_recycle_resource_ids: list[int] = field(default_factory=list)
