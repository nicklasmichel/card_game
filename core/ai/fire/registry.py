from __future__ import annotations

from core.ai.fire.handlers import FIRE_CARD_FAMILIES, FireCardFamily

_FIRE_FAMILY_BY_TEMPLATE_ID: dict[str, FireCardFamily] = {
    family.template_id: family
    for family in FIRE_CARD_FAMILIES
}


def get_fire_card_family(template_id: str) -> FireCardFamily | None:
    return _FIRE_FAMILY_BY_TEMPLATE_ID.get(template_id)
