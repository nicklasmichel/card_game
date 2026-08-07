from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True, frozen=True)
class FireCardFamily:
    template_id: str
    family: str
    rank: int


FIRE_CARD_FAMILIES: tuple[FireCardFamily, ...] = (
    FireCardFamily("fire_ritual_holzvorrat", "ramp", 1),
    FireCardFamily("fire_ritual_kohlevorrat", "ramp", 2),
    FireCardFamily("fire_ritual_glutvision", "draw", 1),
    FireCardFamily("fire_ritual_flammenvision", "draw", 2),
    FireCardFamily("fire_ritual_hitzewelle", "board_wipe", 1),
    FireCardFamily("fire_ritual_feuerwelle", "board_wipe", 2),
    FireCardFamily("fire_spell_wutanfall", "attack_buff", 1),
    FireCardFamily("fire_spell_raserei", "attack_buff", 2),
    FireCardFamily("fire_spell_versengen", "burn", 1),
    FireCardFamily("fire_spell_verbrennen", "burn", 2),
    FireCardFamily("fire_spell_verkohlen", "burn", 3),
)
