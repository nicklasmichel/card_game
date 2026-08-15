from __future__ import annotations

import pygame

from core.models import MatchMode, PHASE_DECLARE_BLOCKERS, PHASE_GAME_OVER
from core.session import LocalPveSession
from multiplayer.client import ClientStatus, NetworkClientSession
from multiplayer.host import AuthoritativeHostSession
from multiplayer.server import DEFAULT_GAME_PORT, HostServer, ServerStatus
from ui.style import CARD_BORDER, HIGHLIGHT, MUTED_TEXT, OVERLAY_COLOR, PANEL_COLOR, TEXT_COLOR


def parse_host_address(value: str) -> tuple[str, int]:
    normalized = value.strip()
    if not normalized:
        raise ValueError("Please enter a host IP address.")
    if ":" not in normalized:
        return normalized, DEFAULT_GAME_PORT
    host, port_text = normalized.rsplit(":", 1)
    if not host:
        raise ValueError("Host address is missing.")
    try:
        port = int(port_text)
    except ValueError as exc:
        raise ValueError("Port must be a number.") from exc
    if not 1 <= port <= 65535:
        raise ValueError("Port must be between 1 and 65535.")
    return host, port


def local_player_has_primary_decision(self) -> bool:
    if self.session.match_mode is MatchMode.PVE:
        return True
    local_player_id = self.session.local_player_id
    if self.engine.phase == PHASE_GAME_OVER:
        return local_player_id == 0
    if self.engine.phase == PHASE_DECLARE_BLOCKERS:
        return self.engine.defending_player.player_id == local_player_id
    return self.engine.active_player.player_id == local_player_id


def select_match_mode(self, selection: str) -> None:
    self.network_error_text = ""
    if selection == "pve":
        replacement = LocalPveSession(auto_start=False)
        self._replace_session(replacement)
        self.network_role = "pve"
        self.match_mode_selection_open = False
        self.join_address_input_open = False
        self.start_player_selection_open = True
        return
    if selection == "host":
        host_session = AuthoritativeHostSession(auto_start=False)
        server = HostServer(
            host_session,
            bind_host="0.0.0.0",
            port=DEFAULT_GAME_PORT,
            host_name="Host",
        )
        try:
            server.start()
        except OSError as exc:
            host_session.close()
            self.network_error_text = f"Could not open port {DEFAULT_GAME_PORT}: {exc}"
            return
        self._replace_session(host_session)
        self.host_server = server
        self.network_role = "host"
        self.match_mode_selection_open = False
        self.join_address_input_open = False
        self.start_player_selection_open = False
        self.network_peer_was_connected = False
        return
    if selection == "join":
        self.join_address_input_open = True
        self.network_error_text = ""
        return
    if selection == "join_connect":
        try:
            host, port = parse_host_address(self.join_address_text)
            client_session = NetworkClientSession.connect(
                host,
                port=port,
                player_name="Guest",
                timeout=4.0,
            )
        except Exception as exc:
            self.network_error_text = f"Connection failed: {exc}"
            return
        self._replace_session(client_session)
        self.network_role = "client"
        self.match_mode_selection_open = False
        self.join_address_input_open = False
        self.start_player_selection_open = False


def replace_session(self, replacement) -> None:
    old_session = self.session
    self.session = replacement
    self.engine = replacement.state
    if old_session is not replacement:
        old_session.close()
    self.clear_drag_state()
    self.buttons.clear()
    self.preview_targets.clear()


def update_network_state(self) -> None:
    if self.network_role == "host" and self.host_server is not None:
        connected = self.host_server.status is ServerStatus.CONNECTED
        if connected and not self.network_peer_was_connected:
            self.network_peer_was_connected = True
            if self.engine.turn_number == 0:
                self.open_start_player_selection()
        elif not connected and self.network_peer_was_connected:
            self.network_peer_was_connected = False
            if self.engine.turn_number == 0:
                self.start_player_selection_open = False


def network_blocks_gameplay(self) -> bool:
    if self.network_role == "host" and self.host_server is not None:
        return self.host_server.status is not ServerStatus.CONNECTED
    if self.network_role == "client":
        status = getattr(self.session, "status", ClientStatus.ERROR)
        return status is not ClientStatus.CONNECTED or self.engine.turn_number == 0
    return False


def shutdown_network(self) -> None:
    if self.host_server is not None:
        self.host_server.stop()
        self.host_server = None


def handle_match_mode_click(self, position: tuple[int, int]) -> None:
    for rect, action in self.match_mode_option_rects:
        if rect.collidepoint(position):
            if action == "join_cancel":
                self.join_address_input_open = False
                self.network_error_text = ""
            else:
                self.select_match_mode(action)
            return


def handle_match_mode_keydown(self, event: pygame.event.Event) -> None:
    if not self.join_address_input_open:
        return
    if event.key == pygame.K_RETURN:
        self.select_match_mode("join_connect")
        return
    if event.key == pygame.K_BACKSPACE:
        self.join_address_text = self.join_address_text[:-1]
        return
    if event.key == pygame.K_ESCAPE:
        self.join_address_input_open = False
        self.network_error_text = ""
        return
    if event.unicode and event.unicode.isprintable() and len(self.join_address_text) < 64:
        self.join_address_text += event.unicode


def draw_match_mode_overlay(self) -> None:
    if not self.match_mode_selection_open:
        return
    overlay = pygame.Surface((self.window_width, self.window_height), pygame.SRCALPHA)
    overlay.fill(OVERLAY_COLOR)
    self.screen.blit(overlay, (0, 0))
    panel_width = min(960, self.window_width - 80)
    panel_height = 430 if not self.join_address_input_open else 500
    panel = pygame.Rect(
        (self.window_width - panel_width) // 2,
        (self.window_height - panel_height) // 2,
        panel_width,
        panel_height,
    )
    pygame.draw.rect(self.screen, PANEL_COLOR, panel, border_radius=10)
    pygame.draw.rect(self.screen, HIGHLIGHT, panel, 2, border_radius=10)
    title_font = pygame.font.SysFont("arial", 38, bold=True)
    button_font = pygame.font.SysFont("arial", 28, bold=True)
    self.blit_centered_text(title_font, "Choose game mode", TEXT_COLOR, pygame.Rect(panel.x, panel.y + 24, panel.width, 44))
    self.blit_centered_text(
        self.font,
        "PvE runs locally. For PvP one player hosts and the other joins.",
        MUTED_TEXT,
        pygame.Rect(panel.x + 30, panel.y + 76, panel.width - 60, 30),
    )
    self.match_mode_option_rects = []
    if not self.join_address_input_open:
        choices = [
            ("PvE vs AI", "pve"),
            ("Host PvP", "host"),
            ("Join PvP", "join"),
        ]
        gap = 22
        width = (panel.width - 60 - gap * 2) // 3
        for index, (label, action) in enumerate(choices):
            rect = pygame.Rect(panel.x + 30 + index * (width + gap), panel.y + 140, width, 190)
            pygame.draw.rect(self.screen, PANEL_COLOR, rect, border_radius=8)
            pygame.draw.rect(self.screen, HIGHLIGHT, rect, 2, border_radius=8)
            self.blit_centered_text(button_font, label, TEXT_COLOR, rect)
            self.match_mode_option_rects.append((rect, action))
    else:
        self.blit_centered_text(
            button_font,
            "Host IP address",
            TEXT_COLOR,
            pygame.Rect(panel.x + 30, panel.y + 126, panel.width - 60, 36),
        )
        input_rect = pygame.Rect(panel.x + 110, panel.y + 180, panel.width - 220, 64)
        pygame.draw.rect(self.screen, (34, 38, 46), input_rect, border_radius=7)
        pygame.draw.rect(self.screen, HIGHLIGHT, input_rect, 2, border_radius=7)
        display_text = self.join_address_text or f"25.x.x.x:{DEFAULT_GAME_PORT}"
        self.blit_centered_text(self.title_font, display_text, TEXT_COLOR, input_rect)
        self.blit_centered_text(
            self.small_font,
            "Use the host's Hamachi IPv4 address. The default port is 47621.",
            MUTED_TEXT,
            pygame.Rect(panel.x + 40, panel.y + 254, panel.width - 80, 28),
        )
        connect_rect = pygame.Rect(panel.centerx - 230, panel.y + 310, 210, 70)
        cancel_rect = pygame.Rect(panel.centerx + 20, panel.y + 310, 210, 70)
        for rect, label, action in (
            (connect_rect, "Connect", "join_connect"),
            (cancel_rect, "Back", "join_cancel"),
        ):
            pygame.draw.rect(self.screen, PANEL_COLOR, rect, border_radius=8)
            pygame.draw.rect(self.screen, HIGHLIGHT, rect, 2, border_radius=8)
            self.blit_centered_text(button_font, label, TEXT_COLOR, rect)
            self.match_mode_option_rects.append((rect, action))
    if self.network_error_text:
        self.blit_centered_text(
            self.small_font,
            self.network_error_text,
            (235, 118, 112),
            pygame.Rect(panel.x + 30, panel.bottom - 64, panel.width - 60, 36),
        )


def draw_network_status_overlay(self) -> None:
    if self.match_mode_selection_open or not self.network_blocks_gameplay():
        return
    overlay = pygame.Surface((self.window_width, self.window_height), pygame.SRCALPHA)
    overlay.fill(OVERLAY_COLOR)
    self.screen.blit(overlay, (0, 0))
    panel = pygame.Rect(
        max(40, (self.window_width - 720) // 2),
        max(40, (self.window_height - 250) // 2),
        720,
        250,
    )
    pygame.draw.rect(self.screen, PANEL_COLOR, panel, border_radius=10)
    pygame.draw.rect(self.screen, HIGHLIGHT, panel, 2, border_radius=10)
    if self.network_role == "host":
        status = self.host_server.status if self.host_server is not None else ServerStatus.ERROR
        title = "Waiting for friend" if status is ServerStatus.LISTENING else "Host network error"
        detail = (
            f"Share your Hamachi IPv4 address. Port: {self.host_server.bound_port}"
            if status is ServerStatus.LISTENING and self.host_server is not None
            else (self.host_server.last_error or "The host server is not available.")
        )
    else:
        status = getattr(self.session, "status", ClientStatus.ERROR)
        if status is ClientStatus.CONNECTED:
            title = "Connected"
            detail = "Waiting for the host to start the match."
        else:
            title = "Connection lost"
            detail = getattr(self.session, "last_error", None) or "The host disconnected."
    self.blit_centered_text(self.title_font, title, TEXT_COLOR, pygame.Rect(panel.x + 20, panel.y + 42, panel.width - 40, 42))
    self.blit_centered_text(self.font, detail, MUTED_TEXT, pygame.Rect(panel.x + 30, panel.y + 112, panel.width - 60, 34))
    self.blit_centered_text(self.small_font, "Press Esc to close GODAO.", MUTED_TEXT, pygame.Rect(panel.x + 30, panel.y + 168, panel.width - 60, 26))
