from __future__ import annotations

from multiplayer.protocol import CommandKind, GameCommand


MAX_PUBLIC_LOG_MESSAGES = 300


def is_public_game_message(message: str) -> bool:
    """Return whether an engine log line is safe and useful for both PvP players."""
    normalized = message.strip()
    if not normalized:
        return False
    if normalized.startswith(("[AI ", "[RUNTIME]", "Choose ", "Optional: ")):
        return False
    if normalized.startswith("This creature "):
        return False
    private_fragments = (
        " selected as blocker.",
        " no longer blocks ",
        " already blocks ",
        " already has a forced blocker.",
        " cannot block ",
        "Choose a blocker first.",
        "Choose a Provoke attacker first.",
        "All block assignments were cleared.",
    )
    if any(fragment in normalized for fragment in private_fragments):
        return False
    if " blocks " in normalized and " with " not in normalized:
        # Tentative human block assignment; it becomes public on confirmation.
        return False
    return True


def public_decision_summary(engine, command: GameCommand) -> list[str]:
    """Describe decisions that are private while editing and public once confirmed."""
    if command.kind is not CommandKind.ACTION:
        return []
    action = command.payload["action"]
    if action == "confirm_attackers" and engine.selected_attackers:
        names = [
            creature.name
            for creature_id in engine.selected_attackers
            if (creature := engine.get_unit_by_id(creature_id)) is not None
        ]
        if names:
            return [f"{engine.active_player.name} attacks with {', '.join(names)}."]
    if action == "confirm_blocks":
        assignments: list[str] = []
        for attacker_id, blocker_id in engine.block_assignments.items():
            if blocker_id is None:
                continue
            attacker = engine.get_unit_by_id(attacker_id)
            blocker = engine.get_unit_by_id(blocker_id)
            if attacker is not None and blocker is not None:
                assignments.append(f"{blocker.name} -> {attacker.name}")
        if assignments:
            return [
                f"{engine.defending_player.name} declares blocks: "
                f"{'; '.join(assignments)}."
            ]
        return [f"{engine.defending_player.name} declares no blocks."]
    return []


def append_public_messages(target: list[str], messages: list[str]) -> None:
    target.extend(message for message in messages if message)
    if len(target) > MAX_PUBLIC_LOG_MESSAGES:
        del target[: len(target) - MAX_PUBLIC_LOG_MESSAGES]
