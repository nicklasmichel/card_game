from __future__ import annotations

from dataclasses import dataclass

from .enums import Ability, CardType, Element


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
    builder_ability: Ability | None = None
    card_type: CardType = CardType.CREATURE
    rules_text: str = ""
    return_to_deck_end_of_turn: bool = False
    cannot_block: bool = False
    must_attack_each_turn: bool = False
    all_attackers_die_bonus: int = 0
    allow_zero_stats: bool = False
    draw_on_attack: int = 0
    draw_on_death: int = 0
    draw_on_player_damage: int = 0
    tap_enemy_creature_on_play: int = 0
    return_other_own_haste_on_combat_death: bool = False
    own_flying_attack_aura: int = 0

    def __post_init__(self) -> None:
        if self.card_type == CardType.CREATURE:
            if self.allow_zero_stats:
                if self.aw < 0 or self.vw < 0:
                    raise ValueError(f"{self.template_id} muss nichtnegative AW-/VW-Werte besitzen.")
            elif self.aw <= 0 or self.vw < 0:
                raise ValueError(f"{self.template_id} muss positiven AW und nichtnegativen VW besitzen.")
            if self.element in {Element.AIR, Element.FIRE, Element.EARTH} and (self.lw is None or self.sw is None):
                raise ValueError(f"{self.template_id} muss explizite LW- und SW-Werte besitzen.")
            if self.effective_lw <= 0 or (self.effective_sw < 0 if self.allow_zero_stats else self.effective_sw <= 0):
                raise ValueError(f"{self.template_id} muss gueltige LW- und SW-Werte besitzen.")
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
