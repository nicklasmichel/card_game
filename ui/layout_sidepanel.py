from __future__ import annotations

from typing import List

import pygame

from core.game_mode import is_builder_mode
from core.models import (
    ButtonSpec,
    CardType,
    Element,
    PHASE_BUILDER_CREATURE,
    PHASE_DECLARE_ATTACKERS,
    PHASE_DECLARE_BLOCKERS,
    PHASE_DICE_BATTLE,
    PHASE_FORCED_DISCARD,
    PHASE_MAIN_1,
    PHASE_MAIN_2,
    PHASE_REACTION,
    PHASE_SPELL_TARGETING,
    SpellEffect,
)
from ui.style import (
    BUTTON_COLOR,
    BUTTON_DISABLED,
    CARD_BORDER,
    HIGHLIGHT,
    MUTED_TEXT,
    PANEL_COLOR,
    SECTION_COLOR,
    TEXT_COLOR,
)


def get_overview_phase_label(phase: str) -> str:
    if phase == PHASE_BUILDER_CREATURE:
        return "Kreatur bauen"
    if phase == PHASE_MAIN_1:
        if is_builder_mode():
            return "Aufbau"
        return "Hauptphase 1"
    if phase == PHASE_MAIN_2:
        return "Hauptphase 2"
    if phase == "Recycle auswaehlen":
        return "Hauptphase"
    if phase in {PHASE_DECLARE_ATTACKERS, PHASE_DECLARE_BLOCKERS, PHASE_DICE_BATTLE}:
        return "Kampf"
    return phase


def get_pending_spell_panel_label(self) -> str | None:
    pending = self.engine.pending_spell_cast
    card = self.engine.get_card_from_pending_spell(pending) if pending is not None else None
    if pending is None or card is None:
        return None
    if card.template.card_type == CardType.RITUAL:
        return "Ritual"
    if self.engine.reaction_window_is_combat_window():
        return "Kampfzauber"
    return "Zauber"


def get_action_panel_title(self) -> str:
    if self.engine.phase == PHASE_BUILDER_CREATURE:
        return "Kreatur bauen"
    if self.engine.phase == PHASE_REACTION:
        return self.engine.get_reaction_window_title()
    if self.engine.phase == PHASE_SPELL_TARGETING:
        panel_label = get_pending_spell_panel_label(self)
        if panel_label is not None:
            return panel_label
    return get_overview_phase_label(self.engine.phase)


def get_action_panel_prompt(self) -> str:
    if is_builder_mode() and self.engine.phase == PHASE_MAIN_1:
        if not self.engine.active_player.main_action_used_this_turn:
            return ""
        return "Greife an oder beende den Zug."
    if self.engine.phase == PHASE_BUILDER_CREATURE:
        return "Verteile bereite Ressourcen auf die neue Kreatur."
    if self.engine.phase == PHASE_REACTION and self.engine.reaction_window_is_combat_window():
        return "Kampfzauber spielen."
    if self.engine.phase == PHASE_SPELL_TARGETING:
        pending = self.engine.pending_spell_cast
        card = self.engine.get_card_from_pending_spell(pending) if pending is not None else None
        if pending is not None and card is not None:
            recycle_cost = card.template.recycle_cost
            selected = len(pending.selected_recycle_resource_ids)
            if recycle_cost > 0:
                return f"Waehle Ressourcen zum Recyclen ({selected}/{recycle_cost})."
            if card.template.sacrifice_own_creature_on_cast:
                return "Waehle eine Opferkreatur."
            if (
                card.template.spell_effect == SpellEffect.GRANT_ATTACK_BONUS_TO_OWN_ATTACKERS_THIS_COMBAT
                and card.template.template_id in {"air_spell_jagdwind", "air_spell_sturmjagd"}
                and pending.selected_combat_bonus_mode is None
            ):
                return "Waehle den Effekt."
            if pending.selected_keyword_ability is None and pending.selected_targets and card.template.spell_effect == SpellEffect.GRANT_HASTE_OR_FLYING_UNTIL_END_OF_TURN:
                return "Waehle den Effekt."
            return "Waehle Zauberziele."
    return self.engine.current_prompt()


def draw_side_panel(self) -> None:
    panel, enemy_piles_rect, log_rect, action_rect, player_piles_rect = self.get_side_panel_layout()
    pygame.draw.rect(self.screen, PANEL_COLOR, panel, border_radius=6)
    self.draw_side_piles(enemy_piles_rect, self.engine.ai_player, self.get_playfield_sections()["enemy_hand"].y + 10)
    self.draw_section_box(log_rect)
    self.draw_side_log(log_rect)
    self.draw_section_box(action_rect)
    self.draw_side_actions(action_rect)
    self.draw_side_piles(player_piles_rect, self.engine.human_player, self.get_playfield_sections()["player_hand"].y + 10)


def get_side_panel_layout(self) -> tuple[pygame.Rect, pygame.Rect, pygame.Rect, pygame.Rect, pygame.Rect]:
    panel = pygame.Rect(self.window_width - self.side_panel_width - 10, 10, self.side_panel_width, self.window_height - 20)
    inner_x = panel.x + 14
    inner_width = panel.width - 28
    section_gap = 10
    inner_height = panel.height - 28
    hand_height = self.get_playfield_sections()["player_hand"].height
    piles_height = min(hand_height, max(self.card_height + 44, inner_height // 5))
    remaining_height = inner_height - piles_height * 2 - section_gap * 4
    log_height = max(140, remaining_height // 2)
    action_height = max(180, remaining_height - log_height)
    used_height = piles_height * 2 + log_height + action_height + section_gap * 4
    slack = max(0, inner_height - used_height)
    log_height += slack // 2
    action_height += slack - (slack // 2)

    enemy_piles_rect = pygame.Rect(inner_x, panel.y + 14, inner_width, piles_height)
    log_rect = pygame.Rect(inner_x, enemy_piles_rect.bottom + section_gap, inner_width, log_height)
    action_rect = pygame.Rect(inner_x, log_rect.bottom + section_gap, inner_width, action_height)
    player_piles_rect = pygame.Rect(inner_x, action_rect.bottom + section_gap, inner_width, piles_height)
    return panel, enemy_piles_rect, log_rect, action_rect, player_piles_rect


def draw_buttons(self) -> None:
    return


def draw_side_overview(self, rect: pygame.Rect) -> None:
    phase_label = get_overview_phase_label(self.engine.phase)
    if is_builder_mode():
        lines = [
            f"Zug: {self.engine.turn_number}",
            f"Am Zug: {self.engine.active_player.name} - {phase_label}",
            f"Spieler LP: {self.engine.human_player.life}",
            f"Gegner LP: {self.engine.ai_player.life}",
            f"Spieler Ressourcen: {self.engine.human_player.available_resources()}/{self.engine.human_player.total_resources()}",
            f"Gegner Ressourcen: {self.engine.ai_player.available_resources()}/{self.engine.ai_player.total_resources()}",
        ]
    else:
        lines = [
            f"Zug: {self.engine.turn_number}",
            f"Am Zug: {self.engine.active_player.name} - {phase_label}",
            f"Spieler LP: {self.engine.human_player.life}",
            f"Gegner LP: {self.engine.ai_player.life}",
            f"Spieler Hand/Deck: {len(self.engine.human_player.hand)}/{len(self.engine.human_player.deck)}",
            f"Gegner Hand/Deck: {len(self.engine.ai_player.hand)}/{len(self.engine.ai_player.deck)}",
        ]
    if self.paused:
        lines.append("Status: Pausiert (Enter)")
    y = rect.y + 28
    for line in lines:
        self.blit_text(self.small_font, line, TEXT_COLOR, rect.x + 12, y)
        y += 16
    if self.engine.phase == PHASE_DECLARE_BLOCKERS:
        target = self.engine.get_unit_by_id(self.engine.selected_attack_target_id) if self.engine.selected_attack_target_id is not None else None
        target_name = target.name if target is not None else "-"
        self.blit_text(self.small_font, f"Blockziel: {target_name}", MUTED_TEXT, rect.x + 12, y + 4)


def draw_side_log(self, rect: pygame.Rect) -> None:
    viewport = pygame.Rect(rect.x + 12, rect.y + 28, rect.width - 36, rect.height - 40)
    self.log_viewport_rect = viewport
    line_height = 22
    line_gap = 4
    wrapped_lines: List[str] = []
    for message in self.engine.log_messages:
        wrapped = self.wrap_text(self.font, message, viewport.width)
        wrapped_lines.extend(wrapped or [""])
        wrapped_lines.append("")
    if wrapped_lines:
        wrapped_lines.pop()
    content_height = len(wrapped_lines) * (line_height + line_gap)
    previous_max_offset = max(0, getattr(self, "log_content_height", 0) - viewport.height)
    was_at_bottom = self.log_scroll_offset >= previous_max_offset
    max_offset = max(0, content_height - viewport.height)
    if was_at_bottom:
        self.log_scroll_offset = max_offset
    else:
        self.log_scroll_offset = max(0, min(self.log_scroll_offset, max_offset))
    self.log_content_height = content_height
    clip_before = self.screen.get_clip()
    self.screen.set_clip(viewport)
    y = viewport.y - self.log_scroll_offset
    for line in wrapped_lines:
        if y + line_height >= viewport.y and y <= viewport.bottom:
            self.blit_text(self.font, line, MUTED_TEXT, viewport.x, y)
        y += line_height + line_gap
    self.screen.set_clip(clip_before)
    track_rect = pygame.Rect(rect.right - 18, viewport.y, 6, viewport.height)
    pygame.draw.rect(self.screen, SECTION_COLOR, track_rect, border_radius=3)
    if content_height > viewport.height and max_offset > 0:
        thumb_height = max(28, int(viewport.height * (viewport.height / content_height)))
        thumb_y = viewport.y + int((viewport.height - thumb_height) * (self.log_scroll_offset / max_offset))
        thumb_rect = pygame.Rect(track_rect.x, thumb_y, track_rect.width, thumb_height)
        pygame.draw.rect(self.screen, HIGHLIGHT, thumb_rect, border_radius=3)
    else:
        pygame.draw.rect(self.screen, MUTED_TEXT, track_rect, border_radius=3)


def get_spell_target_summary(self, card) -> str:
    effect = getattr(card.template, "spell_effect", None)
    if effect == SpellEffect.RETURN_CREATURES_FROM_OWN_DISCARD_TO_HAND:
        return f"{card.template.spell_amount} Kreaturenkarte(n) aus eigenem Ablagestapel"
    if effect == SpellEffect.RETURN_CREATURES_TO_HAND:
        return f"{card.template.spell_amount} beliebige Kreatur(en)"
    if effect == SpellEffect.GRANT_ATTACK_BONUS_TO_OWN_ATTACKERS_THIS_COMBAT:
        return "Keine Ziele"
    if effect == SpellEffect.GRANT_HASTE_OR_FLYING_UNTIL_END_OF_TURN:
        return "Beliebige Kreatur, danach Schnell oder Fliegend"
    if effect == SpellEffect.RETURN_OWN_AND_ENEMY_CREATURE_TO_HAND:
        return "Eigene Kreatur und gegnerische Kreatur"
    if effect == SpellEffect.RETURN_OWN_FIGHTING_CREATURE_TO_HAND:
        return "Eigene kaempfende Kreatur"
    if effect == SpellEffect.DISCARD_HAND_AND_DRAW:
        return "Keine Ziele"
    target_mode = getattr(card.template, "target_mode", None)
    if target_mode is None:
        return "-"
    mode_name = getattr(target_mode, "name", "")
    if mode_name == "NONE":
        return "Keine Ziele"
    if mode_name == "CREATURE":
        return "Beliebige Kreatur"
    if mode_name == "CREATURE_OR_PLAYER":
        return "Beliebige Kreatur oder Beschwoerer"
    return str(target_mode.value)


def get_spell_effect_summary(self, card) -> str:
    text = getattr(card.template, "rules_text", "").strip()
    if text:
        return text
    effect = getattr(card.template, "spell_effect", None)
    return effect.value if effect is not None else "-"


def format_target_ref(self, target) -> str:
    if target is None:
        return "-"
    if target.target_type == "player":
        player = self.engine.get_player_by_id(target.player_id or 0)
        return player.name
    if target.target_type == "creature":
        creature = self.engine.get_unit_by_id(target.creature_id or -1)
        return creature.name if creature is not None else "Kreatur nicht mehr im Spiel"
    if target.target_type == "discard_card":
        card = self.engine.resolve_target_discard_card(target)
        if card is None:
            return "Karte nicht mehr im Ablagestapel"
        return f"{card.template.name} ({self.engine.human_player.name if card in self.engine.human_player.discard_pile else self.engine.ai_player.name})"
    return target.target_type


def get_pending_target_summary(self) -> str:
    pending = self.engine.pending_spell_cast
    if pending is None:
        return "-"
    chosen: list[str] = []
    if pending.selected_sacrifice_creature_id is not None:
        creature = self.engine.get_unit_by_id(pending.selected_sacrifice_creature_id)
        chosen.append(f"Opfer: {creature.name if creature is not None else 'ausgewaehlt'}")
    for target in pending.selected_targets:
        chosen.append(f"Ziel: {self.format_target_ref(target)}")
    if pending.selected_recycle_resource_ids:
        chosen.append(
            f"Recycle: {len(pending.selected_recycle_resource_ids)}"
            f"/{self.engine.get_card_from_pending_spell(pending).template.recycle_cost if self.engine.get_card_from_pending_spell(pending) is not None else 0}"
        )
    if pending.selected_keyword_ability is not None:
        chosen.append(f"Effekt: {pending.selected_keyword_ability.value}")
    if pending.selected_combat_bonus_mode is not None:
        card = self.engine.get_card_from_pending_spell(pending)
        attack_bonus = card.template.combat_aw_bonus if card is not None else 0
        damage_bonus = card.template.combat_sw_bonus if card is not None else 0
        label = (
            f"+{attack_bonus} Angriff"
            if pending.selected_combat_bonus_mode == "attack"
            else f"+{damage_bonus} Schaden"
        )
        chosen.append(f"Effekt: {label}")
    return " | ".join(chosen) if chosen else "Noch nichts ausgewaehlt"


def get_stack_lines(self) -> list[str]:
    if not self.engine.spell_stack:
        return ["Leer"]
    lines: list[str] = []
    for depth, item in enumerate(reversed(self.engine.spell_stack), start=1):
        target_text = ", ".join(self.format_target_ref(target) for target in item.targets) if item.targets else "ohne Ziel"
        lines.append(f"{depth}. {item.controller.name}: {item.source_card.template.name} -> {target_text}")
    return lines


def get_legal_reaction_lines(self) -> list[str]:
    if self.engine.phase != PHASE_REACTION:
        return []
    if self.engine.reaction_priority_player_id != self.engine.human_player.player_id:
        return ["Gegner entscheidet."]
    legal = [
        card.template.name
        for card in self.engine.human_player.hand
        if self.engine.can_react_with_card(self.engine.human_player, card)
    ]
    if not legal:
        return ["Nur Passen ist legal."]
    return legal


def get_selected_spell_lines(self) -> list[str]:
    card = self.engine.get_selected_hand_card()
    if card is None or card.template.card_type == CardType.CREATURE:
        return []
    lines = [
        f"Karte: {card.template.name}",
        f"Typ: {card.template.card_type.value}",
        f"Element: {card.template.element.value}",
        f"Kosten: {self.engine.format_card_cost(card.template.cost)}",
        f"Ziele: {get_spell_target_summary(self, card)}",
        f"Effekt: {get_spell_effect_summary(self, card)}",
    ]
    if card.template.card_type == CardType.SPELL and card.template.reaction_trigger is not None:
        lines.append(f"Ausloeser: {card.template.reaction_trigger.value}")
    return lines


def get_action_detail_sections(self) -> list[tuple[str, list[str]]]:
    sections: list[tuple[str, list[str]]] = []
    pending = self.engine.pending_spell_cast
    if self.engine.phase == PHASE_BUILDER_CREATURE and self.engine.pending_builder_creature is not None:
        build = self.engine.pending_builder_creature
        sections.append(
            (
                "Neue Kreatur",
                [
                    f"Angriff: {build.aw}",
                    f"Verteidigung: {build.vw}",
                    f"Schaden: {build.sw}",
                    f"Leben: {build.lw}",
                    f"Kosten: {self.engine.builder_creature_build_cost()} / {build.available_resources} verfuegbar",
                    f"Bereit danach: {self.engine.builder_remaining_ready_resources()}",
                ],
            )
        )
        return sections
    if self.engine.phase == PHASE_SPELL_TARGETING and pending is not None:
        return sections
    if self.engine.phase == PHASE_SPELL_TARGETING:
        sections.append(("Zauberziele", [get_pending_target_summary(self)]))
    return sections


def draw_action_detail_sections(self, rect: pygame.Rect, start_y: int, max_bottom: int | None = None) -> int:
    sections = get_action_detail_sections(self)
    if not sections:
        return start_y
    y = start_y
    for title, lines in sections:
        content = [title]
        for line in lines:
            wrapped = self.wrap_text(self.small_font, line, rect.width - 24)
            content.extend(wrapped or [""])
        height = 16 + len(content) * 16 + 8
        box_rect = pygame.Rect(rect.x + 12, y, rect.width - 24, height)
        if max_bottom is not None and box_rect.bottom > max_bottom:
            break
        pygame.draw.rect(self.screen, SECTION_COLOR, box_rect, border_radius=6)
        pygame.draw.rect(self.screen, CARD_BORDER, box_rect, 1, border_radius=6)
        line_y = box_rect.y + 8
        self.blit_text(self.small_font, title, HIGHLIGHT, box_rect.x + 8, line_y)
        line_y += 18
        first = True
        for line in content[1:]:
            color = TEXT_COLOR if first else MUTED_TEXT
            self.blit_text(self.small_font, line, color, box_rect.x + 8, line_y)
            line_y += 16
            first = False
        y = box_rect.bottom + 8
    return y


def draw_side_actions(self, rect: pygame.Rect) -> None:
    action_specs = self.engine.get_button_specs()
    phase_label = get_action_panel_title(self)
    self.blit_text(
        self.title_font,
        f"{self.engine.turn_number} | {self.engine.active_player.name} - {phase_label}",
        TEXT_COLOR,
        rect.x + 12,
        rect.y + 12,
    )
    prompt_rect = pygame.Rect(rect.x + 12, rect.y + 52, rect.width - 24, 64)
    self.blit_wrapped_text(self.font, get_action_panel_prompt(self), MUTED_TEXT, prompt_rect, 22)
    detail_start_y = draw_action_detail_sections(self, rect, prompt_rect.bottom + 8)
    button_margin = 12
    width = rect.width - button_margin * 2
    height = 36
    gap = 10
    start_x = rect.x + button_margin
    if self.engine.phase == PHASE_BUILDER_CREATURE:
        stat_rows = min(4, len(action_specs) // 2)
        trailing_buttons = max(0, len(action_specs) - stat_rows * 2)
        button_total_height = stat_rows * height + max(0, stat_rows - 1) * gap
        if trailing_buttons:
            button_total_height += gap + trailing_buttons * height + max(0, trailing_buttons - 1) * gap
    else:
        button_total_height = len(action_specs) * height + max(0, len(action_specs) - 1) * gap
    button_start_y = rect.bottom - 12 - button_total_height
    detail_start_y = draw_action_detail_sections(self, rect, prompt_rect.bottom + 8, button_start_y - 8)
    start_y = button_start_y
    if self.engine.phase == PHASE_BUILDER_CREATURE:
        half_gap = 8
        half_width = (width - half_gap) // 2
        current_y = start_y
        stat_rows = min(4, len(action_specs) // 2)
        for row_index in range(stat_rows):
            left_spec = action_specs[row_index * 2]
            right_spec = action_specs[row_index * 2 + 1]
            left_rect = pygame.Rect(start_x, current_y, half_width, height)
            right_rect = pygame.Rect(start_x + half_width + half_gap, current_y, half_width, height)
            for button_rect, spec in ((left_rect, left_spec), (right_rect, right_spec)):
                pygame.draw.rect(self.screen, BUTTON_COLOR if spec.enabled else BUTTON_DISABLED, button_rect, border_radius=6)
                pygame.draw.rect(self.screen, CARD_BORDER, button_rect, 2, border_radius=6)
                self.blit_centered_text(self.font, spec.label, TEXT_COLOR, button_rect)
                self.buttons.append((button_rect, spec))
            current_y += height + gap
        if stat_rows and len(action_specs) > stat_rows * 2:
            current_y += 0
        for spec in action_specs[stat_rows * 2:]:
            button_rect = pygame.Rect(start_x, current_y, width, height)
            pygame.draw.rect(self.screen, BUTTON_COLOR if spec.enabled else BUTTON_DISABLED, button_rect, border_radius=6)
            pygame.draw.rect(self.screen, CARD_BORDER, button_rect, 2, border_radius=6)
            self.blit_centered_text(self.font, spec.label, TEXT_COLOR, button_rect)
            self.buttons.append((button_rect, spec))
            current_y += height + gap
        return
    for index, spec in enumerate(action_specs):
        button_rect = pygame.Rect(start_x, start_y + index * (height + gap), width, height)
        pygame.draw.rect(self.screen, BUTTON_COLOR if spec.enabled else BUTTON_DISABLED, button_rect, border_radius=6)
        pygame.draw.rect(self.screen, CARD_BORDER, button_rect, 2, border_radius=6)
        self.blit_centered_text(self.font, spec.label, TEXT_COLOR, button_rect)
        self.buttons.append((button_rect, spec))


def draw_side_piles(self, rect: pygame.Rect, player, card_y: int) -> None:
    if is_builder_mode():
        return
    card_width = self.card_width
    card_height = self.card_height
    available_width = max(0, rect.width - card_width * 2)
    side_gap = max(0, available_width // 3)
    middle_gap = max(0, rect.width - card_width * 2 - side_gap * 2)
    deck_x = rect.x + side_gap
    discard_x = deck_x + card_width + middle_gap

    top_deck_card = player.deck[-1] if player.deck else None
    if top_deck_card is not None or player.summoner_key:
        if top_deck_card is not None:
            deck_surface = self.build_resource_back_surface(top_deck_card.template.element, False)
        else:
            fallback_elements = {
                "fire": Element.FIRE,
                "water": Element.WATER,
                "earth": Element.EARTH,
                "air": Element.AIR,
            }
            deck_surface = self.build_resource_back_surface(fallback_elements.get(player.summoner_key, Element.AIR), False)
        deck_rect = pygame.Rect(deck_x, card_y, card_width, card_height)
        self.screen.blit(deck_surface, deck_rect.topleft)
        pygame.draw.rect(self.screen, CARD_BORDER, deck_rect, 2, border_radius=9)
        deck_badge_rect = pygame.Rect(deck_rect.centerx - 34, deck_rect.centery - 26, 68, 52)
        self.draw_card_badge(self.screen, deck_badge_rect, str(len(player.deck)), self.font, self.get_think_progress(player))
        self.preview_targets.append((deck_rect, lambda player=player: self.build_preview_deck_surface(player), lambda: []))
        if player.player_id == self.engine.ai_player.player_id:
            self.click_targets["enemy_deck"].append((deck_rect.copy(), player.player_id))

    top_discard = player.discard_pile[-1] if player.discard_pile else None
    discard_rect = pygame.Rect(discard_x, card_y, card_width, card_height)
    if top_discard is not None:
        preview_surface = self.build_card_surface(
            template_id=top_discard.template.template_id,
            title=top_discard.template.name,
            cost=top_discard.template.cost,
            stats=self.get_display_template_stats(top_discard.template) if top_discard.template.card_type == CardType.CREATURE else None,
            element=top_discard.template.element,
            type_line=self.get_creature_type_line(top_discard.template),
            line_one=self.get_card_ability_lines(top_discard.template)[0],
            line_two=self.get_card_ability_lines(top_discard.template)[1],
            accent_color=(186, 177, 154),
            frame_color=(191, 161, 92),
            tapped=False,
            selected=False,
        )
        self.screen.blit(preview_surface, discard_rect.topleft)
        pygame.draw.rect(self.screen, CARD_BORDER, discard_rect, 2, border_radius=9)
        self.preview_targets.append((discard_rect, lambda card=top_discard: self.build_preview_hand_card_surface(card), lambda card=top_discard: self.get_card_preview_ability_details(card.template)))
    else:
        pygame.draw.rect(self.screen, PANEL_COLOR, discard_rect, border_radius=9)
        pygame.draw.rect(self.screen, CARD_BORDER, discard_rect, 2, border_radius=9)


def handle_log_scroll(self, delta: int) -> None:
    if self.log_viewport_rect.width <= 0 or self.log_viewport_rect.height <= 0:
        return
    mouse_pos = pygame.mouse.get_pos()
    if not self.log_viewport_rect.collidepoint(mouse_pos):
        return
    self.log_scroll_offset = max(0, self.log_scroll_offset + delta)


def blit_text(self, font: pygame.font.Font, text: str, color, x: int, y: int) -> None:
    self.screen.blit(font.render(text, True, color), (x, y))


def draw_section_box(self, rect: pygame.Rect, title: str = "") -> None:
    pygame.draw.rect(self.screen, SECTION_COLOR, rect, border_radius=6)
    pygame.draw.rect(self.screen, CARD_BORDER, rect, 1, border_radius=6)
    if title:
        self.blit_text(self.small_font, title, MUTED_TEXT, rect.x + 10, rect.y + 6)
