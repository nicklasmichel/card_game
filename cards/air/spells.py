from __future__ import annotations

from core.models import CardCost, CardTemplate, CardType, Element, SpellEffect, SpellTargetMode


AIR_SPELLS = [
    CardTemplate(
        template_id="air_spell_ausweichen",
        name="Ausweichen",
        cost=CardCost(resources=1),
        aw=0,
        vw=0,
        element=Element.AIR,
        card_type=CardType.SPELL,
        spell_effect=SpellEffect.RETURN_CREATURES_TO_HAND,
        target_mode=SpellTargetMode.CREATURE,
        spell_amount=1,
        rules_text="Nimm 1 Kreatur auf die Hand ihres Besitzers zurueck.",
    ),
    CardTemplate(
        template_id="air_spell_windstoss",
        name="Windstoss",
        cost=CardCost(resources=2),
        aw=0,
        vw=0,
        element=Element.AIR,
        card_type=CardType.SPELL,
        spell_effect=SpellEffect.RETURN_CREATURES_TO_HAND,
        target_mode=SpellTargetMode.CREATURE,
        spell_amount=2,
        rules_text="Nimm 2 Kreaturen auf die Haende ihrer Besitzer zurueck.",
    ),
    CardTemplate(
        template_id="air_spell_boeenschub",
        name="Boeenschub",
        cost=CardCost(resources=1),
        aw=0,
        vw=0,
        element=Element.AIR,
        card_type=CardType.SPELL,
        spell_effect=SpellEffect.GRANT_ATTACK_BONUS_TO_OWN_ATTACKERS_THIS_COMBAT,
        target_mode=SpellTargetMode.NONE,
        spell_amount=1,
        rules_text="Deine angreifenden Kreaturen erhalten fuer diesen Kampf +1 AW.",
    ),
    CardTemplate(
        template_id="air_spell_windrausch",
        name="Windrausch",
        cost=CardCost(resources=2),
        aw=0,
        vw=0,
        element=Element.AIR,
        card_type=CardType.SPELL,
        spell_effect=SpellEffect.GRANT_ATTACK_BONUS_TO_OWN_ATTACKERS_THIS_COMBAT,
        target_mode=SpellTargetMode.NONE,
        spell_amount=2,
        rules_text="Deine angreifenden Kreaturen erhalten fuer diesen Kampf +2 AW.",
    ),
]
