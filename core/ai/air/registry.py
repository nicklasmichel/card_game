from __future__ import annotations

from core.ai.air.creature_handlers import SPECIALIZED_AIR_CREATURE_HANDLERS, AirCreatureHandler
from core.ai.air.handlers import SPECIALIZED_AIR_HANDLERS, AirCardHandler

_AIR_HANDLER_BY_TEMPLATE_ID: dict[str, AirCardHandler] = {
    handler.template_id: handler
    for handler in SPECIALIZED_AIR_HANDLERS
}

_AIR_CREATURE_HANDLER_BY_TEMPLATE_ID: dict[str, AirCreatureHandler] = {
    handler.template_id: handler
    for handler in SPECIALIZED_AIR_CREATURE_HANDLERS
}


def get_air_card_handler(template_id: str) -> AirCardHandler | None:
    return _AIR_HANDLER_BY_TEMPLATE_ID.get(template_id)


def get_air_creature_handler(template_id: str) -> AirCreatureHandler | None:
    return _AIR_CREATURE_HANDLER_BY_TEMPLATE_ID.get(template_id)
