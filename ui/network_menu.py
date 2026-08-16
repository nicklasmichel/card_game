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


def validate_player_name(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError("Please enter your player name.")
    if len(normalized) > 32:
        raise ValueError("Player names may contain at most 32 characters.")
    return normalized


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
        replacement.start_new_game()
        return
    if selection in {"host", "join"}:
        self.network_setup_mode = selection
        self.network_active_input = "name"
        self.join_address_input_open = True
        self.network_error_text = ""
        return
    if selection == "host_start":
        try:
            player_name = validate_player_name(self.network_player_name_text)
        except ValueError as exc:
            self.network_error_text = str(exc)
            return
        host_session = AuthoritativeHostSession(auto_start=False)
        server = HostServer(
            host_session,
            bind_host="0.0.0.0",
            port=DEFAULT_GAME_PORT,
            host_name=player_name,
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
        self.network_setup_mode = None
        self.network_peer_was_connected = False
        return
    if selection == "join_connect":
        try:
            player_name = validate_player_name(self.network_player_name_text)
            host, port = parse_host_address(self.join_address_text)
            client_session = NetworkClientSession.connect(
                host,
                port=port,
                player_name=player_name,
                timeout=4.0,
            )
        except Exception as exc:
            self.network_error_text = f"Connection failed: {exc}"
            return
        self._replace_session(client_session)
        self.network_role = "client"
        self.match_mode_selection_open = False
        self.join_address_input_open = False
        self.network_setup_mode = None


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
                self.session.start_new_game()
        elif not connected and self.network_peer_was_connected:
            self.network_peer_was_connected = False


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
                self.network_setup_mode = None
                self.network_error_text = ""
            elif action == "focus_name":
                self.network_active_input = "name"
            elif action == "focus_address":
                self.network_active_input = "address"
            else:
                self.select_match_mode(action)
            return


def handle_match_mode_keydown(self, event: pygame.event.Event) -> None:
    if not self.join_address_input_open:
        return
    if event.key == pygame.K_RETURN:
        action = "host_start" if self.network_setup_mode == "host" else "join_connect"
        self.select_match_mode(action)
        return
    if event.key == pygame.K_TAB and self.network_setup_mode == "join":
        self.network_active_input = (
            "address" if self.network_active_input == "name" else "name"
        )
        return
    if event.key == pygame.K_BACKSPACE:
        if self.network_active_input == "name":
            self.network_player_name_text = self.network_player_name_text[:-1]
        else:
            self.join_address_text = self.join_address_text[:-1]
        return
    if event.key == pygame.K_ESCAPE:
        self.join_address_input_open = False
        self.network_setup_mode = None
        self.network_error_text = ""
        return
    if event.unicode and event.unicode.isprintable():
        if self.network_active_input == "name" and len(self.network_player_name_text) < 32:
            self.network_player_name_text += event.unicode
        elif self.network_active_input == "address" and len(self.join_address_text) < 64:
            self.join_address_text += event.unicode


def draw_match_mode_overlay(self) -> None:
    if not self.match_mode_selection_open:
        return
    s = self.scale_ui
    overlay = pygame.Surface((self.window_width, self.window_height), pygame.SRCALPHA)
    overlay.fill(OVERLAY_COLOR)
    self.screen.blit(overlay, (0, 0))
    panel_width = min(s(960), self.window_width - s(80))
    panel_height = s(430) if not self.join_address_input_open else (
        s(590) if self.network_setup_mode == "join" else s(500)
    )
    panel = pygame.Rect(
        (self.window_width - panel_width) // 2,
        (self.window_height - panel_height) // 2,
        panel_width,
        panel_height,
    )
    pygame.draw.rect(self.screen, PANEL_COLOR, panel, border_radius=s(10))
    pygame.draw.rect(self.screen, HIGHLIGHT, panel, s(2), border_radius=s(10))
    title_font = pygame.font.SysFont("arial", self.scale_font(38), bold=True)
    button_font = pygame.font.SysFont("arial", self.scale_font(28), bold=True)
    overlay_title = "Choose game mode"
    if self.network_setup_mode == "host":
        overlay_title = "Host PvP"
    elif self.network_setup_mode == "join":
        overlay_title = "Join PvP"
    self.blit_centered_text(title_font, overlay_title, TEXT_COLOR, pygame.Rect(panel.x, panel.y + s(24), panel.width, s(44)))
    self.blit_centered_text(
        self.font,
        "PvE runs locally. For PvP one player hosts and the other joins.",
        MUTED_TEXT,
        pygame.Rect(panel.x + s(30), panel.y + s(76), panel.width - s(60), s(30)),
    )
    self.match_mode_option_rects = []
    if not self.join_address_input_open:
        choices = [
            ("PvE vs AI", "pve"),
            ("Host PvP", "host"),
            ("Join PvP", "join"),
        ]
        gap = s(22)
        width = (panel.width - s(60) - gap * 2) // 3
        for index, (label, action) in enumerate(choices):
            rect = pygame.Rect(panel.x + s(30) + index * (width + gap), panel.y + s(140), width, s(190))
            pygame.draw.rect(self.screen, PANEL_COLOR, rect, border_radius=s(8))
            pygame.draw.rect(self.screen, HIGHLIGHT, rect, s(2), border_radius=s(8))
            self.blit_centered_text(button_font, label, TEXT_COLOR, rect)
            self.match_mode_option_rects.append((rect, action))
    else:
        name_label_rect = pygame.Rect(panel.x + s(30), panel.y + s(112), panel.width - s(60), s(30))
        self.blit_centered_text(
            button_font,
            "Your player name",
            TEXT_COLOR,
            name_label_rect,
        )
        name_rect = pygame.Rect(panel.x + s(110), panel.y + s(150), panel.width - s(220), s(58))
        pygame.draw.rect(self.screen, (34, 38, 46), name_rect, border_radius=s(7))
        pygame.draw.rect(
            self.screen,
            HIGHLIGHT if self.network_active_input == "name" else CARD_BORDER,
            name_rect,
            s(2),
            border_radius=s(7),
        )
        name_display = self.network_player_name_text or "Your name"
        self.blit_centered_text(
            self.title_font,
            name_display,
            TEXT_COLOR if self.network_player_name_text else MUTED_TEXT,
            name_rect,
        )
        self.match_mode_option_rects.append((name_rect, "focus_name"))

        button_y = panel.y + s(280)
        primary_label = "Start hosting"
        primary_action = "host_start"
        if self.network_setup_mode == "join":
            self.blit_centered_text(
                button_font,
                "Host IP address",
                TEXT_COLOR,
                pygame.Rect(panel.x + s(30), panel.y + s(226), panel.width - s(60), s(30)),
            )
            address_rect = pygame.Rect(panel.x + s(110), panel.y + s(264), panel.width - s(220), s(58))
            pygame.draw.rect(self.screen, (34, 38, 46), address_rect, border_radius=s(7))
            pygame.draw.rect(
                self.screen,
                HIGHLIGHT if self.network_active_input == "address" else CARD_BORDER,
                address_rect,
                s(2),
                border_radius=s(7),
            )
            address_display = self.join_address_text or f"25.x.x.x:{DEFAULT_GAME_PORT}"
            self.blit_centered_text(
                self.title_font,
                address_display,
                TEXT_COLOR if self.join_address_text else MUTED_TEXT,
                address_rect,
            )
            self.match_mode_option_rects.append((address_rect, "focus_address"))
            self.blit_centered_text(
                self.small_font,
                "Use the host's Hamachi IPv4 address. Tab switches fields.",
                MUTED_TEXT,
                pygame.Rect(panel.x + s(40), panel.y + s(330), panel.width - s(80), s(28)),
            )
            button_y = panel.y + s(382)
            primary_label = "Connect"
            primary_action = "join_connect"
        else:
            self.blit_centered_text(
                self.small_font,
                f"Your friend connects through Hamachi on port {DEFAULT_GAME_PORT}.",
                MUTED_TEXT,
                pygame.Rect(panel.x + s(40), panel.y + s(222), panel.width - s(80), s(28)),
            )

        connect_rect = pygame.Rect(panel.centerx - s(230), button_y, s(210), s(70))
        cancel_rect = pygame.Rect(panel.centerx + s(20), button_y, s(210), s(70))
        for rect, label, action in (
            (connect_rect, primary_label, primary_action),
            (cancel_rect, "Back", "join_cancel"),
        ):
            pygame.draw.rect(self.screen, PANEL_COLOR, rect, border_radius=s(8))
            pygame.draw.rect(self.screen, HIGHLIGHT, rect, s(2), border_radius=s(8))
            self.blit_centered_text(button_font, label, TEXT_COLOR, rect)
            self.match_mode_option_rects.append((rect, action))
    if self.network_error_text:
        self.blit_centered_text(
            self.small_font,
            self.network_error_text,
            (235, 118, 112),
            pygame.Rect(panel.x + s(30), panel.bottom - s(64), panel.width - s(60), s(36)),
        )


def draw_network_status_overlay(self) -> None:
    if self.match_mode_selection_open or self.network_role not in {"host", "client"}:
        return
    if not self.network_blocks_gameplay():
        if self.network_role == "host":
            peer_name = self.host_server.remote_name if self.host_server is not None else None
        else:
            peer_name = getattr(self.session, "host_name", None)
        badge = pygame.Rect(self.scale_ui(18), self.scale_ui(18), self.scale_ui(310), self.scale_ui(38))
        pygame.draw.rect(self.screen, PANEL_COLOR, badge, border_radius=self.scale_ui(8))
        pygame.draw.rect(self.screen, HIGHLIGHT, badge, self.scale_ui(2), border_radius=self.scale_ui(8))
        label = f"PvP connected - {peer_name or 'opponent'}"
        self.blit_centered_text(self.small_font, label, TEXT_COLOR, badge)
        return
    overlay = pygame.Surface((self.window_width, self.window_height), pygame.SRCALPHA)
    overlay.fill(OVERLAY_COLOR)
    self.screen.blit(overlay, (0, 0))
    s = self.scale_ui
    panel = pygame.Rect(
        (self.window_width - s(720)) // 2,
        (self.window_height - s(250)) // 2,
        s(720),
        s(250),
    )
    pygame.draw.rect(self.screen, PANEL_COLOR, panel, border_radius=s(10))
    pygame.draw.rect(self.screen, HIGHLIGHT, panel, s(2), border_radius=s(10))
    if self.network_role == "host":
        status = self.host_server.status if self.host_server is not None else ServerStatus.ERROR
        if status is ServerStatus.LISTENING and self.host_server is not None:
            if self.host_server.has_connected:
                title = "Connection lost - game paused"
                remote_name = self.host_server.last_remote_name or "Your friend"
                detail = f"Waiting for {remote_name} to reconnect automatically."
            else:
                title = "Waiting for friend"
                detail = f"Share your Hamachi IPv4 address. Port: {self.host_server.bound_port}"
        else:
            title = "Host network error"
            detail = (
                self.host_server.last_error
                if self.host_server is not None
                else "The host server is not available."
            ) or "The host server is not available."
    else:
        status = getattr(self.session, "status", ClientStatus.ERROR)
        if status is ClientStatus.CONNECTED:
            title = "Connected"
            detail = "Waiting for the host to start the match."
        elif status is ClientStatus.RECONNECTING:
            title = "Reconnecting - game paused"
            attempt = getattr(self.session, "reconnect_attempt", 0)
            detail = f"Trying to reach {self.session.host_name} again (attempt {max(1, attempt)})."
        else:
            title = "Connection error - game paused"
            detail = getattr(self.session, "last_error", None) or "The host disconnected."
    self.blit_centered_text(self.title_font, title, TEXT_COLOR, pygame.Rect(panel.x + s(20), panel.y + s(42), panel.width - s(40), s(42)))
    self.blit_centered_text(self.font, detail, MUTED_TEXT, pygame.Rect(panel.x + s(30), panel.y + s(112), panel.width - s(60), s(34)))
    self.blit_centered_text(self.small_font, "Press Esc to close GODAO.", MUTED_TEXT, pygame.Rect(panel.x + s(30), panel.y + s(168), panel.width - s(60), s(26)))
