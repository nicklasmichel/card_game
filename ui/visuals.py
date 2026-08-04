from __future__ import annotations

from typing import Dict

import pygame

from core.models import CardInstance


def consume_visual_events(self) -> None:
    if not self.engine.pending_visual_events:
        self.prune_finished_visuals()
        return
    now = pygame.time.get_ticks()
    popup_totals: Dict[int, dict] = {}
    next_direct_attack_start_by_target: Dict[int, int] = {}

    for popup in self.damage_popups:
        if popup.get("type") != "player_damage" or popup.get("attacker_id") is None:
            continue
        target_player_id = popup["target_player_id"]
        next_direct_attack_start_by_target[target_player_id] = max(
            next_direct_attack_start_by_target.get(target_player_id, now),
            popup["started_at_ms"] + 1550,
        )
    for animation in self.creature_lunges.values():
        target_player_id = animation["target_player_id"]
        next_direct_attack_start_by_target[target_player_id] = max(
            next_direct_attack_start_by_target.get(target_player_id, now),
            animation["started_at_ms"] + 1550,
        )

    for event in self.engine.pending_visual_events:
        if event.get("type") == "creature_damage":
            source_element = event.get("source_element")
            color = self.get_element_color(source_element) if source_element is not None else (255, 255, 255)
            self.damage_popups.append(
                {
                    "type": "creature_damage",
                    "target_role": event["target_role"],
                    "amount": event["amount"],
                    "color": color,
                    "started_at_ms": now,
                }
            )
            continue
        if event.get("type") == "recycle_reveal":
            continue
        if event.get("type") != "player_damage":
            continue
        source_element = event.get("source_element")
        color = self.get_element_color(source_element) if source_element is not None else (255, 255, 255)
        target_player_id = event["target_player_id"]
        attacker_id = event.get("attacker_id")
        if attacker_id is not None:
            started_at_ms = next_direct_attack_start_by_target.get(target_player_id, now)
            next_direct_attack_start_by_target[target_player_id] = started_at_ms + 1550
            self.damage_popups.append(
                {
                    "type": "player_damage",
                    "target_player_id": target_player_id,
                    "amount": event["amount"],
                    "color": color,
                    "started_at_ms": started_at_ms,
                    "attacker_id": attacker_id,
                }
            )
            self.creature_lunges[attacker_id] = {
                "target_player_id": target_player_id,
                "started_at_ms": started_at_ms,
            }
            continue
        popup_entry = popup_totals.setdefault(
            target_player_id,
            {
                "type": "player_damage",
                "target_player_id": target_player_id,
                "amount": 0,
                "color": color,
                "started_at_ms": now,
            },
        )
        popup_entry["amount"] += event["amount"]
    self.damage_popups.extend(popup_totals.values())
    self.engine.pending_visual_events.clear()
    self.prune_finished_visuals()


def prune_finished_visuals(self) -> None:
    now = self.pause_started_at_ms if self.paused and self.pause_started_at_ms is not None else pygame.time.get_ticks()
    self.damage_popups = [
        popup
        for popup in self.damage_popups
        if now - popup["started_at_ms"] <= 3000
    ]
    self.recycle_reveals = [
        reveal
        for reveal in self.recycle_reveals
        if now - reveal["started_at_ms"] <= 3000
    ]
    self.creature_lunges = {
        creature_id: animation
        for creature_id, animation in self.creature_lunges.items()
        if now - animation["started_at_ms"] <= 1550
    }


def draw_damage_popups(self) -> None:
    now = self.pause_started_at_ms if self.paused and self.pause_started_at_ms is not None else pygame.time.get_ticks()
    for popup in self.damage_popups:
        if popup.get("type") != "player_damage":
            continue
        target_player = self.engine.players[popup["target_player_id"]]
        summoner_rect = self.get_summoner_rect_for_player(target_player)
        progress = min(1.0, max(0.0, (now - popup["started_at_ms"]) / 3000.0))
        y_offset = int(46 * progress)
        alpha = 255 if progress < 0.8 else max(0, int(255 * (1.0 - (progress - 0.8) / 0.2)))
        text = f"-{popup['amount']}"
        text_surface = self.title_font.render(text, True, popup["color"])
        shadow_surface = self.title_font.render(text, True, (0, 0, 0))
        text_surface.set_alpha(alpha)
        shadow_surface.set_alpha(alpha)
        text_rect = text_surface.get_rect(center=(summoner_rect.centerx, summoner_rect.y + int(self.card_height * 0.56) - y_offset))
        self.screen.blit(shadow_surface, text_rect.move(2, 2))
        self.screen.blit(text_surface, text_rect)


def draw_combat_damage_popups(self) -> None:
    now = self.pause_started_at_ms if self.paused and self.pause_started_at_ms is not None else pygame.time.get_ticks()
    for popup in self.damage_popups:
        if popup.get("type") != "creature_damage":
            continue
        target_rect = self.combat_overlay_card_rects.get(popup["target_role"])
        if target_rect is None:
            continue
        progress = min(1.0, max(0.0, (now - popup["started_at_ms"]) / 3000.0))
        y_offset = int(54 * progress)
        alpha = 255 if progress < 0.8 else max(0, int(255 * (1.0 - (progress - 0.8) / 0.2)))
        text = f"-{popup['amount']}"
        text_surface = self.title_font.render(text, True, popup["color"])
        shadow_surface = self.title_font.render(text, True, (0, 0, 0))
        text_surface.set_alpha(alpha)
        shadow_surface.set_alpha(alpha)
        text_rect = text_surface.get_rect(center=(target_rect.centerx, target_rect.bottom - 20 - y_offset))
        self.screen.blit(shadow_surface, text_rect.move(2, 2))
        self.screen.blit(text_surface, text_rect)


def draw_creature_overlays(self) -> None:
    for creature, is_human, draw_x, draw_y, selected, extra_line, attacking, target_key in self.creature_overlay_draws:
        rect = self.draw_creature_card(creature, is_human, draw_x, draw_y, selected, extra_line, attacking)
        if self.last_preview_builder is not None:
            self.preview_targets.append((rect, self.last_preview_builder))
        self.click_targets[target_key].append((rect, creature.unit_id))


def draw_recycle_reveals(self) -> None:
    return
