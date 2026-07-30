from __future__ import annotations

import os
from typing import Dict, List, Tuple

import pygame

from game_logic import GameEngine
from models import (
    ButtonSpec,
    PHASE_DECLARE_BLOCKERS,
    PHASE_DICE_BATTLE,
    PHASE_GAME_OVER,
    PHASE_MULLIGAN,
    PHASE_ORDER_BLOCKERS,
)


FPS = 60
WINDOW_WIDTH = 1920
WINDOW_HEIGHT = 1080

BG_COLOR = (28, 31, 36)
PANEL_COLOR = (42, 47, 56)
SECTION_COLOR = (36, 40, 48)
CARD_COLOR = (238, 232, 218)
CARD_BORDER = (74, 63, 49)
CARD_TEXT_DARK = (28, 28, 28)
TEXT_COLOR = (240, 240, 240)
MUTED_TEXT = (190, 190, 190)
HIGHLIGHT = (88, 174, 255)
BUTTON_COLOR = (70, 95, 130)
BUTTON_DISABLED = (70, 70, 74)
ENEMY_CARD_COLOR = (177, 98, 98)
PLAYER_CARD_COLOR = (98, 151, 109)
RESOURCE_COLOR = (140, 126, 82)
OVERLAY_COLOR = (18, 20, 24, 220)
CARD_HEADER = (214, 204, 182)
CARD_ART = (120, 127, 143)
CARD_RULEBOX = (227, 221, 205)
CARD_FRAME_GOLD = (191, 161, 92)
CARD_BADGE_DARK = (58, 52, 44)
CARD_BADGE_LIGHT = (244, 239, 228)
CARD_TYPE_BAR = (204, 194, 171)
CARD_SHADOW = (0, 0, 0, 70)

BASE_CARD_WIDTH = 96
BASE_CARD_HEIGHT = 134
BASE_CARD_GAP = 10


class TcgPrototypeApp:
    def __init__(self) -> None:
        os.environ["SDL_VIDEO_CENTERED"] = "1"
        pygame.init()
        display_info = pygame.display.Info()
        self.window_width = min(WINDOW_WIDTH, max(1280, display_info.current_w - 80))
        self.window_height = min(WINDOW_HEIGHT, max(720, display_info.current_h - 120))
        self.screen = pygame.display.set_mode(
            (self.window_width, self.window_height),
        )
        self.card_width = 128 if self.window_width >= 1800 else 112
        self.card_height = int(self.card_width * 1.4)
        self.card_gap = 14 if self.window_width >= 1800 else 10
        self.side_panel_width = 380 if self.window_width >= 1800 else 350
        self.main_area_width = self.window_width - self.side_panel_width - 30
        pygame.display.set_caption("TCG Prototype")
        self.clock = pygame.time.Clock()
        self.font = pygame.font.SysFont("arial", 18)
        self.small_font = pygame.font.SysFont("arial", 15)
        self.title_font = pygame.font.SysFont("arial", 24, bold=True)
        self.engine = GameEngine()
        self.buttons: List[Tuple[pygame.Rect, ButtonSpec]] = []
        self.click_targets: Dict[str, List[Tuple[pygame.Rect, int]]] = {
            "hand": [],
            "player_units": [],
            "enemy_units": [],
            "human_dice": [],
            "order_blockers": [],
            "mulligan_hand": [],
        }

    def run(self) -> None:
        running = True
        while running:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                    running = False
                elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    self.handle_mouse_click(event.pos)

            self.engine.process_ai_turn()
            if self.engine.exit_requested:
                running = False
            self.draw()
            self.clock.tick(FPS)

        pygame.quit()

    def handle_mouse_click(self, position: tuple[int, int]) -> None:
        for rect, spec in self.buttons:
            if spec.enabled and rect.collidepoint(position):
                self.engine.handle_action(spec.action)
                return
        for area, targets in self.click_targets.items():
            for rect, item_id in targets:
                if rect.collidepoint(position):
                    area_name = "hand" if area == "mulligan_hand" else area
                    self.engine.handle_click(area_name, item_id)
                    return

    def draw(self) -> None:
        self.screen.fill(BG_COLOR)
        for key in self.click_targets:
            self.click_targets[key] = []
        self.buttons.clear()

        self.draw_top_bar()
        self.draw_enemy_area()
        self.draw_player_area()
        self.draw_side_panel()
        self.draw_buttons()

        if self.engine.phase == PHASE_MULLIGAN:
            self.draw_mulligan_overlay()
        if self.engine.pending_order is not None:
            self.draw_block_order_overlay()
        if self.engine.pending_dice_battle is not None:
            self.draw_dice_battle_overlay()
        if self.engine.phase == PHASE_GAME_OVER:
            self.draw_game_over_overlay()

        pygame.display.flip()

    def draw_top_bar(self) -> None:
        rect = pygame.Rect(10, 10, self.window_width - 20, 72)
        pygame.draw.rect(self.screen, PANEL_COLOR, rect, border_radius=6)
        self.blit_text(self.title_font, f"Zug {self.engine.turn_number}", TEXT_COLOR, 24, 18)
        self.blit_text(self.font, f"Am Zug: {self.engine.active_player.name}", TEXT_COLOR, 200, 20)
        self.blit_text(self.font, f"Phase: {self.engine.phase}", TEXT_COLOR, 410, 20)
        self.blit_text(self.font, f"Spieler LP: {self.engine.human_player.life}", TEXT_COLOR, 730, 20)
        self.blit_text(self.font, f"Gegner LP: {self.engine.ai_player.life}", TEXT_COLOR, 940, 20)
        self.blit_text(self.font, self.engine.current_prompt(), MUTED_TEXT, 24, 46)

    def draw_enemy_area(self) -> None:
        side_panel_x = self.window_width - self.side_panel_width - 10
        rect = pygame.Rect(10, 90, side_panel_x - 20, 280)
        pygame.draw.rect(self.screen, PANEL_COLOR, rect, border_radius=6)
        self.blit_text(self.title_font, "Gegner", TEXT_COLOR, 24, 104)
        self.blit_text(
            self.font,
            (
                f"Handkarten: {len(self.engine.ai_player.hand)} | Deck: {len(self.engine.ai_player.deck)} | "
                f"Ressourcen: {self.engine.ai_player.available_resources()}/{self.engine.ai_player.total_resources()}"
            ),
            TEXT_COLOR,
            24,
            132,
        )
        resource_rect = pygame.Rect(rect.x + 14, rect.y + 62, rect.width - 28, 64)
        units_rect = pygame.Rect(rect.x + 14, rect.y + 136, rect.width - 28, 130)
        self.draw_section_box(resource_rect, "Ressourcen")
        self.draw_section_box(units_rect, "Units")
        self.draw_resources(self.engine.ai_player.resources, resource_rect.x + 12, resource_rect.y + 26)
        self.draw_units(self.engine.ai_player.battlefield, False, "enemy_units", units_rect.x + 12, units_rect.y + 26, units_rect.width - 24)

    def draw_player_area(self) -> None:
        side_panel_x = self.window_width - self.side_panel_width - 10
        rect = pygame.Rect(10, 382, side_panel_x - 20, self.window_height - 392)
        pygame.draw.rect(self.screen, PANEL_COLOR, rect, border_radius=6)
        self.blit_text(self.title_font, "Spieler", TEXT_COLOR, 24, 396)
        self.blit_text(
            self.font,
            (
                f"Handkarten: {len(self.engine.human_player.hand)} | Deck: {len(self.engine.human_player.deck)} | "
                f"Ressourcen: {self.engine.human_player.available_resources()}/{self.engine.human_player.total_resources()}"
            ),
            TEXT_COLOR,
            24,
            424,
        )
        resource_rect = pygame.Rect(rect.x + 14, rect.y + 62, rect.width - 28, 64)
        units_rect = pygame.Rect(rect.x + 14, rect.y + 136, rect.width - 28, 176)
        hand_rect = pygame.Rect(rect.x + 14, rect.y + 322, rect.width - 28, rect.height - 336)
        self.draw_section_box(resource_rect, "Ressourcen")
        self.draw_section_box(units_rect, "Units")
        self.draw_section_box(hand_rect, "Hand")
        self.draw_resources(self.engine.human_player.resources, resource_rect.x + 12, resource_rect.y + 26)
        self.draw_units(self.engine.human_player.battlefield, True, "player_units", units_rect.x + 12, units_rect.y + 26, units_rect.width - 24)
        self.draw_hand(self.engine.human_player.hand, hand_rect.x + 12, hand_rect.y + 28, hand_rect.width - 24)

    def draw_resources(self, resources, start_x: int, start_y: int) -> None:
        resource_gap = 76 if self.window_width >= 1800 else 70
        for index, resource in enumerate(resources):
            rect = pygame.Rect(start_x + index * resource_gap, start_y, 68, 44)
            color = RESOURCE_COLOR if not resource.tapped else BUTTON_DISABLED
            pygame.draw.rect(self.screen, color, rect, border_radius=4)
            pygame.draw.rect(self.screen, CARD_BORDER, rect, 2, border_radius=4)
            self.blit_text(self.small_font, "R", TEXT_COLOR, rect.x + 8, rect.y + 7)
            self.blit_text(self.small_font, resource.source_name[:7], TEXT_COLOR, rect.x + 18, rect.y + 7)
            self.blit_text(
                self.small_font,
                "Getappt" if resource.tapped else "Bereit",
                MUTED_TEXT,
                rect.x + 6,
                rect.y + 23,
            )

    def draw_units(self, units, is_human: bool, target_key: str, start_x: int, start_y: int, lane_width: int) -> None:
        column_step = self.card_height + self.card_gap + 10
        columns = max(1, lane_width // column_step)
        for index, unit in enumerate(units):
            column = index % columns
            row = index // columns
            x = start_x + column * column_step
            y = start_y + row * (self.card_height + 22)
            selected = False
            if target_key == "player_units" and unit.unit_id in self.engine.selected_attackers:
                selected = True
            if target_key == "player_units" and unit.unit_id == self.engine.selected_blocker_id:
                selected = True
            if self.engine.pending_order is not None and unit.unit_id in self.engine.pending_order.chosen_order:
                selected = True
            extra_line = ""
            if target_key == "enemy_units" and unit.unit_id in self.engine.block_assignments:
                blockers = len(self.engine.block_assignments[unit.unit_id])
                if blockers:
                    extra_line = f"Blocker {blockers}"
            rect = self.draw_unit_card(unit, is_human, x, y, selected, extra_line)
            self.click_targets[target_key].append((rect, unit.unit_id))

    def draw_hand(self, hand, start_x: int, start_y: int, available_width: int) -> None:
        card_step = self.card_width + self.card_gap
        if hand:
            total_width = len(hand) * self.card_width + (len(hand) - 1) * self.card_gap
            if total_width > available_width:
                card_step = max(26, (available_width - self.card_width) // max(1, len(hand) - 1))
        for index, card in enumerate(hand):
            x = start_x + index * card_step
            rect = self.draw_hand_card(card, x, start_y, card.instance_id in self.engine.selected_hand_ids)
            self.click_targets["hand"].append((rect, card.instance_id))

    def draw_side_panel(self) -> None:
        rect = pygame.Rect(self.window_width - self.side_panel_width - 10, 90, self.side_panel_width, self.window_height - 100)
        pygame.draw.rect(self.screen, PANEL_COLOR, rect, border_radius=6)
        self.blit_text(self.title_font, "Log", TEXT_COLOR, rect.x + 14, 104)
        y = 138
        for line in self.engine.log_messages[-18:]:
            y = self.blit_wrapped_text(self.small_font, line, MUTED_TEXT, pygame.Rect(rect.x + 14, y, rect.width - 28, 100), 18)
            y += 4
        if self.engine.phase == PHASE_DECLARE_BLOCKERS and self.engine.selected_blocker_id is not None:
            blocker = self.engine.get_unit_by_id(self.engine.selected_blocker_id)
            if blocker is not None:
                self.blit_text(self.font, f"Ausgewaehlter Blocker: {blocker.name}", TEXT_COLOR, rect.x + 14, rect.bottom - 40)

    def draw_buttons(self) -> None:
        specs = self.engine.get_button_specs()
        x = self.window_width - self.side_panel_width + 6 - 10
        y = self.window_height - 92
        width = (self.side_panel_width - 34) // 2
        height = 36
        gap = 10
        for index, spec in enumerate(specs):
            rect = pygame.Rect(x + (index % 2) * (width + gap), y + (index // 2) * (height + gap), width, height)
            pygame.draw.rect(self.screen, BUTTON_COLOR if spec.enabled else BUTTON_DISABLED, rect, border_radius=6)
            pygame.draw.rect(self.screen, CARD_BORDER, rect, 2, border_radius=6)
            self.blit_centered_text(self.small_font, spec.label, TEXT_COLOR, rect)
            self.buttons.append((rect, spec))

    def draw_mulligan_overlay(self) -> None:
        overlay = pygame.Surface((self.window_width, self.window_height), pygame.SRCALPHA)
        overlay.fill(OVERLAY_COLOR)
        self.screen.blit(overlay, (0, 0))
        panel = pygame.Rect(
            max(40, (self.window_width - 1240) // 2),
            max(40, (self.window_height - 520) // 2),
            1240,
            520,
        )
        pygame.draw.rect(self.screen, PANEL_COLOR, panel, border_radius=8)
        pygame.draw.rect(self.screen, HIGHLIGHT, panel, 2, border_radius=8)
        self.blit_text(self.title_font, "Starthand und Mulligan", TEXT_COLOR, panel.x + 30, panel.y + 26)
        self.blit_text(
            self.font,
            "Klicke beliebige Karten an, um sie einmalig ins Deck zurueckzumischen und neu zu ziehen.",
            MUTED_TEXT,
            panel.x + 30,
            panel.y + 58,
        )
        for index, card in enumerate(self.engine.human_player.hand):
            mulligan_step = self.card_width + 32
            rect = self.draw_hand_card(
                card,
                panel.x + 30 + index * mulligan_step,
                panel.y + 140,
                card.instance_id in self.engine.selected_hand_ids,
            )
            self.click_targets["mulligan_hand"].append((rect, card.instance_id))

    def draw_block_order_overlay(self) -> None:
        overlay = pygame.Surface((self.window_width, self.window_height), pygame.SRCALPHA)
        overlay.fill(OVERLAY_COLOR)
        self.screen.blit(overlay, (0, 0))
        panel = pygame.Rect(
            max(40, (self.window_width - 780) // 2),
            max(40, (self.window_height - 420) // 2),
            780,
            420,
        )
        pygame.draw.rect(self.screen, PANEL_COLOR, panel, border_radius=8)
        pygame.draw.rect(self.screen, HIGHLIGHT, panel, 2, border_radius=8)
        attacker = self.engine.get_unit_by_id(self.engine.pending_order.attacker_id)
        name = attacker.name if attacker is not None else "Angreifer"
        self.blit_text(self.title_font, f"Blockreihenfolge fuer {name}", TEXT_COLOR, panel.x + 26, panel.y + 28)
        self.blit_text(self.font, "Klicke die Blocker in der gewuenschten Reihenfolge an.", MUTED_TEXT, panel.x + 26, panel.y + 62)
        for index, blocker_id in enumerate(self.engine.pending_order.blocker_ids):
            blocker = self.engine.get_unit_by_id(blocker_id)
            if blocker is None:
                continue
            rect = pygame.Rect(panel.x + 30, panel.y + 100 + index * 62, 720, 48)
            pygame.draw.rect(self.screen, ENEMY_CARD_COLOR, rect, border_radius=6)
            pygame.draw.rect(self.screen, CARD_BORDER, rect, 2, border_radius=6)
            if blocker_id in self.engine.pending_order.chosen_order:
                pygame.draw.rect(self.screen, HIGHLIGHT, rect, 3, border_radius=6)
                order_index = self.engine.pending_order.chosen_order.index(blocker_id) + 1
                prefix = f"{order_index}."
            else:
                prefix = f"{index + 1}."
            self.blit_text(self.font, prefix, TEXT_COLOR, rect.x + 10, rect.y + 14)
            self.blit_text(
                self.font,
                f"{blocker.name} - {blocker.aw_vw} - noch {blocker.current_hp} LP",
                TEXT_COLOR,
                rect.x + 56,
                rect.y + 14,
            )
            self.click_targets["order_blockers"].append((rect, blocker_id))

    def draw_dice_battle_overlay(self) -> None:
        battle = self.engine.pending_dice_battle
        if battle is None:
            return
        overlay = pygame.Surface((self.window_width, self.window_height), pygame.SRCALPHA)
        overlay.fill(OVERLAY_COLOR)
        self.screen.blit(overlay, (0, 0))
        panel = pygame.Rect(
            max(40, (self.window_width - 1180) // 2),
            max(40, (self.window_height - 680) // 2),
            1180,
            680,
        )
        pygame.draw.rect(self.screen, PANEL_COLOR, panel, border_radius=8)
        pygame.draw.rect(self.screen, HIGHLIGHT, panel, 2, border_radius=8)

        attacker = self.engine.get_unit_by_id(battle.attacker_id)
        blocker = self.engine.get_unit_by_id(battle.blocker_id)
        if attacker is None or blocker is None:
            return
        human_is_attacker = battle.attacker_owner == self.engine.human_player.player_id
        human_unit = attacker if human_is_attacker else blocker
        enemy_unit = blocker if human_is_attacker else attacker
        human_dice = battle.attacker_dice if human_is_attacker else battle.blocker_dice
        enemy_dice = battle.blocker_dice if human_is_attacker else battle.attacker_dice

        self.blit_text(self.title_font, f"Wuerfelkampf: {attacker.name} gegen {blocker.name}", TEXT_COLOR, panel.x + 30, panel.y + 32)
        self.blit_text(
            self.font,
            f"Eigene Unit: {human_unit.name} ({human_unit.aw_vw}) HP {human_unit.current_hp}/{human_unit.vw}",
            TEXT_COLOR,
            panel.x + 30,
            panel.y + 64,
        )
        self.blit_text(
            self.font,
            f"Gegnerische Unit: {enemy_unit.name} ({enemy_unit.aw_vw}) HP {enemy_unit.current_hp}/{enemy_unit.vw}",
            TEXT_COLOR,
            panel.x + 30,
            panel.y + 92,
        )
        self.blit_text(
            self.font,
            f"Verdeckte Gegnerwuerfel: {sum(1 for die in enemy_dice if not die.used)}",
            MUTED_TEXT,
            panel.x + 30,
            panel.y + 120,
        )

        available_human_dice = [die for die in human_dice if not die.used]
        self.blit_text(self.title_font, "Eigene verfuegbare Wuerfel", TEXT_COLOR, panel.x + 30, panel.y + 158)
        for index, die in enumerate(available_human_dice):
            rect = pygame.Rect(panel.x + 30 + (index % 4) * 270, panel.y + 194 + (index // 4) * 56, 248, 44)
            pygame.draw.rect(self.screen, BUTTON_COLOR, rect, border_radius=6)
            pygame.draw.rect(self.screen, CARD_BORDER, rect, 2, border_radius=6)
            self.blit_text(self.font, f"{index + 1}. {die.display()}", TEXT_COLOR, rect.x + 10, rect.y + 10)
            self.click_targets["human_dice"].append((rect, index))

        self.blit_text(self.title_font, "Bisherige Vergleiche", TEXT_COLOR, panel.x + 30, panel.y + 320)
        y = panel.y + 356
        for record in battle.history[-5:]:
            self.blit_text(
                self.small_font,
                f"Runde {record.round_number}: {record.human_unit_name} {record.human_result} | "
                f"{record.enemy_unit_name} {record.enemy_result}",
                TEXT_COLOR,
                panel.x + 30,
                y,
            )
            self.blit_text(self.small_font, record.outcome_text, MUTED_TEXT, panel.x + 30, y + 18)
            y += 44

    def draw_game_over_overlay(self) -> None:
        overlay = pygame.Surface((self.window_width, self.window_height), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 150))
        self.screen.blit(overlay, (0, 0))
        panel = pygame.Rect(
            max(40, (self.window_width - 780) // 2),
            max(40, (self.window_height - 360) // 2),
            780,
            360,
        )
        pygame.draw.rect(self.screen, PANEL_COLOR, panel, border_radius=8)
        pygame.draw.rect(self.screen, HIGHLIGHT, panel, 2, border_radius=8)
        self.blit_centered_text(self.title_font, "Spielende", TEXT_COLOR, pygame.Rect(panel.x, panel.y + 20, panel.width, 30))
        self.blit_centered_text(self.font, self.engine.game_over_text, TEXT_COLOR, pygame.Rect(panel.x + 20, panel.y + 60, panel.width - 40, 30))
        y = panel.y + 104
        for line in self.engine.game_over_summary_lines[:8]:
            self.blit_text(self.font, line, MUTED_TEXT, panel.x + 36, y)
            y += 28

    def blit_text(self, font: pygame.font.Font, text: str, color, x: int, y: int) -> None:
        self.screen.blit(font.render(text, True, color), (x, y))

    def draw_section_box(self, rect: pygame.Rect, title: str) -> None:
        pygame.draw.rect(self.screen, SECTION_COLOR, rect, border_radius=6)
        pygame.draw.rect(self.screen, CARD_BORDER, rect, 1, border_radius=6)
        self.blit_text(self.small_font, title, MUTED_TEXT, rect.x + 10, rect.y + 6)

    def draw_hand_card(self, card, x: int, y: int, selected: bool, note: str = "") -> pygame.Rect:
        surface = self.build_card_surface(
            title=card.template.name,
            cost=card.template.cost,
            stats=f"{card.template.aw}/{card.template.vw}",
            line_one="Unit",
            line_two=note,
            accent_color=(186, 177, 154),
            frame_color=CARD_FRAME_GOLD,
            tapped=False,
            selected=selected,
        )
        rect = pygame.Rect(x, y, self.card_width, self.card_height)
        self.screen.blit(surface, rect.topleft)
        return rect

    def draw_unit_card(
        self,
        unit,
        is_human: bool,
        x: int,
        y: int,
        selected: bool,
        extra_line: str = "",
    ) -> pygame.Rect:
        accent = PLAYER_CARD_COLOR if is_human else ENEMY_CARD_COLOR
        line_one = f"HP {unit.current_hp}/{unit.vw}"
        line_two = f"{unit.short_status()} | S {unit.damage_taken}"
        if extra_line:
            line_two = extra_line
        surface = self.build_card_surface(
            title=unit.name,
            cost=unit.cost,
            stats=unit.aw_vw,
            line_one=line_one,
            line_two=line_two,
            accent_color=accent,
            frame_color=accent,
            tapped=unit.tapped,
            selected=selected,
        )
        width = self.card_height if unit.tapped else self.card_width
        height = self.card_width if unit.tapped else self.card_height
        rect = pygame.Rect(x, y, width, height)
        self.screen.blit(surface, rect.topleft)
        return rect

    def build_card_surface(
        self,
        title: str,
        cost: int,
        stats: str,
        line_one: str,
        line_two: str,
        accent_color,
        frame_color,
        tapped: bool,
        selected: bool,
    ) -> pygame.Surface:
        base = pygame.Surface((self.card_width, self.card_height), pygame.SRCALPHA)
        shadow_rect = pygame.Rect(4, 5, self.card_width - 6, self.card_height - 6)
        pygame.draw.rect(base, CARD_SHADOW, shadow_rect, border_radius=9)

        outer_rect = pygame.Rect(0, 0, self.card_width, self.card_height)
        inner_rect = pygame.Rect(4, 4, self.card_width - 8, self.card_height - 8)
        header_rect = pygame.Rect(7, 7, self.card_width - 14, 24)
        art_rect = pygame.Rect(9, 34, self.card_width - 18, int(self.card_height * 0.38))
        type_rect = pygame.Rect(9, art_rect.bottom + 4, self.card_width - 18, 14)
        text_rect = pygame.Rect(9, type_rect.bottom + 4, self.card_width - 18, 22)
        footer_rect = pygame.Rect(9, self.card_height - 20, self.card_width - 18, 12)

        pygame.draw.rect(base, frame_color, outer_rect, border_radius=9)
        pygame.draw.rect(base, CARD_BORDER, outer_rect, 2, border_radius=9)
        pygame.draw.rect(base, CARD_COLOR, inner_rect, border_radius=7)
        pygame.draw.rect(base, CARD_HEADER, header_rect, border_radius=5)
        pygame.draw.rect(base, accent_color, art_rect, border_radius=4)
        pygame.draw.rect(base, CARD_TYPE_BAR, type_rect, border_radius=3)
        pygame.draw.rect(base, CARD_RULEBOX, text_rect, border_radius=3)
        pygame.draw.rect(base, CARD_RULEBOX, footer_rect, border_radius=3)

        self.draw_art_panel(base, art_rect, accent_color)

        cost_center = (self.card_width - 18, 19)
        pygame.draw.circle(base, CARD_BADGE_LIGHT, cost_center, 11)
        pygame.draw.circle(base, CARD_BORDER, cost_center, 11, 2)

        attack_rect = pygame.Rect(8, self.card_height - 26, 24, 18)
        defense_rect = pygame.Rect(self.card_width - 32, self.card_height - 26, 24, 18)
        pygame.draw.rect(base, CARD_BADGE_DARK, attack_rect, border_radius=6)
        pygame.draw.rect(base, CARD_BADGE_DARK, defense_rect, border_radius=6)
        center_badge = pygame.Rect(35, self.card_height - 26, self.card_width - 70, 18)
        pygame.draw.rect(base, CARD_BADGE_LIGHT, center_badge, border_radius=5)

        aw_text, vw_text = stats.split("/", maxsplit=1)
        self.blit_text_to_surface(base, self.small_font, self.fit_text(self.small_font, title, self.card_width - 42), CARD_TEXT_DARK, 10, 12)
        self.blit_text_to_surface(base, self.small_font, str(cost), CARD_TEXT_DARK, self.card_width - 22, 12)
        self.blit_centered_text_to_surface(base, self.small_font, "UNIT", CARD_TEXT_DARK, type_rect)
        self.blit_text_to_surface(base, self.small_font, self.fit_text(self.small_font, line_one, self.card_width - 28), CARD_TEXT_DARK, 12, text_rect.y + 3)
        self.blit_text_to_surface(base, self.small_font, self.fit_text(self.small_font, line_two, self.card_width - 28), CARD_TEXT_DARK, 12, footer_rect.y - 1)
        self.blit_centered_text_to_surface(base, self.small_font, aw_text, CARD_BADGE_LIGHT, attack_rect)
        self.blit_centered_text_to_surface(base, self.small_font, vw_text, CARD_BADGE_LIGHT, defense_rect)

        if selected:
            pygame.draw.rect(base, HIGHLIGHT, pygame.Rect(0, 0, self.card_width, self.card_height), 3, border_radius=8)

        if tapped:
            return pygame.transform.rotate(base, -90)
        return base

    def blit_text_to_surface(self, surface: pygame.Surface, font: pygame.font.Font, text: str, color, x: int, y: int) -> None:
        surface.blit(font.render(text, True, color), (x, y))

    def blit_centered_text_to_surface(
        self,
        surface: pygame.Surface,
        font: pygame.font.Font,
        text: str,
        color,
        rect: pygame.Rect,
    ) -> None:
        text_surface = font.render(text, True, color)
        surface.blit(text_surface, text_surface.get_rect(center=rect.center))

    def fit_text(self, font: pygame.font.Font, text: str, max_width: int) -> str:
        if font.size(text)[0] <= max_width:
            return text
        shortened = text
        while shortened and font.size(shortened + "...")[0] > max_width:
            shortened = shortened[:-1]
        return shortened + "..." if shortened else text[:1]

    def draw_art_panel(self, surface: pygame.Surface, rect: pygame.Rect, accent_color) -> None:
        art_top = tuple(min(255, channel + 38) for channel in accent_color)
        art_bottom = tuple(max(0, channel - 28) for channel in accent_color)
        for offset in range(rect.height):
            ratio = offset / max(1, rect.height - 1)
            color = tuple(
                int(art_top[index] * (1 - ratio) + art_bottom[index] * ratio)
                for index in range(3)
            )
            pygame.draw.line(surface, color, (rect.x, rect.y + offset), (rect.right - 1, rect.y + offset))
        pygame.draw.rect(surface, CARD_BORDER, rect, 1, border_radius=4)
        symbol_rect = pygame.Rect(rect.x + 20, rect.y + 10, rect.width - 40, rect.height - 20)
        pygame.draw.ellipse(surface, CARD_BADGE_LIGHT, symbol_rect, 2)
        pygame.draw.line(surface, CARD_BADGE_LIGHT, (symbol_rect.x + 8, symbol_rect.bottom - 8), (symbol_rect.centerx, symbol_rect.y + 8), 2)
        pygame.draw.line(surface, CARD_BADGE_LIGHT, (symbol_rect.centerx, symbol_rect.y + 8), (symbol_rect.right - 8, symbol_rect.bottom - 8), 2)

    def blit_centered_text(self, font: pygame.font.Font, text: str, color, rect: pygame.Rect) -> None:
        surface = font.render(text, True, color)
        self.screen.blit(surface, surface.get_rect(center=rect.center))

    def blit_wrapped_text(self, font: pygame.font.Font, text: str, color, rect: pygame.Rect, line_height: int) -> int:
        words = text.split()
        lines: List[str] = []
        current = ""
        for word in words:
            proposal = word if not current else f"{current} {word}"
            if font.size(proposal)[0] <= rect.width:
                current = proposal
            else:
                lines.append(current)
                current = word
        if current:
            lines.append(current)
        y = rect.y
        for line in lines:
            self.blit_text(font, line, color, rect.x, y)
            y += line_height
        return y


def main() -> None:
    app = TcgPrototypeApp()
    app.run()


if __name__ == "__main__":
    main()
