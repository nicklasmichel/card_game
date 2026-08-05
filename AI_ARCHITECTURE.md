# AI Architecture

## Oeffentliche Einstiegspunkte

- `core.ai.simple_ai.HeuristicStrategicAI`
- `core.ai.simple_ai.SimpleAI` als Alias
- `core.ai.context.build_ai_context`
- `core.ai_logic` als Kompatibilitaetsfassade

## Verzeichnisstruktur

- `core/ai/common.py`: allgemeine KI-Auswahl, Blocken, Recycle, Wuerfelstrategie
- `core/ai/plan_manager.py`: alleiniger Besitzer des aktiven `TurnPlan`
- `core/ai/strategy_registry.py`: waehlt pro Element die passende Strategie
- `core/ai/turn_planner.py`: orchestriert Zugkandidaten und deren Auswahl
- `core/ai/reaction_planner.py`: kapselt Reaktionsentscheidungen
- `core/ai/assessment_component.py`: kompakter Assessment-Zugang
- `core/ai/effect_evaluator_component.py`: kompakter Effektbewertungs-Zugang
- `core/ai/strategies/base.py`: allgemeine Strategievertraege und Gewichte
- `core/ai/strategies/air.py`: Luft-Strategie, Modusauswahl und strategischer Snapshot
- `core/ai/strategies/generic.py`: generische Fallback-Strategie
- `core/ai/context.py`: kompakter, regelkonformer KI-Kontext ohne verdeckte Informationen
- `core/ai/types.py`: kompakte Begruendungstypen fuer aeltere API-Stellen

## Entscheidungsablauf

1. Engine ruft `HeuristicStrategicAI` auf.
2. `StrategyRegistry` liefert die passende Strategie oder den generischen Fallback.
3. `TurnPlanner` erzeugt Kandidaten und der `PlanManager` aktiviert den besten `TurnPlan`.
4. `ReactionPlanner` arbeitet mit aktivem Plan, Reservierungen und `ReactionIntent`.
5. Nach Kartenziehen, Zufall oder gegnerischer Reaktion darf die KI neu planen.

## Komponenten und Verantwortlichkeiten

- `HeuristicStrategicAI`: zentraler Orchestrator, oeffentliche KI-Einstiegspunkte, Komponentenverdrahtung
- `PlanManager`: aktivieren, verwerfen, Fortschritt markieren, letzten Plan archivieren
- `StrategyRegistry`: Strategieauswahl pro Element
- `TurnPlanner`: vollstaendige Zugkandidaten erzeugen und vergleichen
- `AssessmentComponent`: kompakter Einstieg in Zustands- und Kampfabschaetzungen
- `EffectEvaluatorComponent`: kompakter Einstieg in lokale Effektbewertungen
- `ReactionPlanner`: Reaktionszauber und Zielwahl ueber aktiven Plan

## Planverwaltung und Mixins

- `PlanManager` ist alleiniger Besitzer des aktiven `TurnPlan`.
- Aktive Luft-Orchestrierung liegt in `TurnPlanner`, `ReactionPlanner`, `AssessmentComponent` und `EffectEvaluatorComponent`.
- Versteckte MRO-Ketten sind nicht mehr Teil des aktiven Laufzeitpfads.

## Neues Element ergaenzen

1. Neue Strategieklasse implementieren.
2. Strategie in `StrategyRegistry.register(...)` anbinden.
3. Elementeigene Planungs-, Bewertungs- und Reaktionsmodule unter `core/ai/<element>/` kapseln.
4. Orchestrierung, `PlanManager` und Engine-Schnittstellen unveraendert lassen.

## Informationsgrenzen der KI

- Keine Kenntnis verdeckter Karten
- Keine Kenntnis zukuenftiger Ziehkarten
- Keine Kenntnis unbekannter Wuerfelergebnisse
- Bewertung nur aus sichtbarem Spielzustand, Deckstruktur und Heuristiken
