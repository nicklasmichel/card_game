# KI-Module

Zweck: allgemeine KI-Orchestrierung, Planverwaltung und elementbezogene Strategien sauber trennen.

Oeffentliche Einstiegspunkte:
- `core.ai.simple_ai.HeuristicStrategicAI`
- `core.ai.simple_ai.SimpleAI` als Kompatibilitaetsalias
- `core.ai.context.build_ai_context`
- `core.ai.types.ActionCandidate`

Wichtige Dateien:
- `common.py`: allgemeine Auswahlregeln, Blocken, Recycle, Wuerfelstrategie
- `plan_manager.py`: alleiniger Besitzer des aktiven `TurnPlan`
- `strategy_registry.py`: Zuordnung von Elementen zu Strategien mit Fallback
- `turn_planner.py`: orchestriert vollstaendige Zugkandidatenplanung
- `reaction_planner.py`: kapselt Reaktionsauswahl auf Basis des aktiven Plans
- `assessment_component.py`: kompakter Zugang zu Zustands- und Kampfabschaetzungen
- `effect_evaluator_component.py`: kompakter Zugang zu lokalen Effektbewertungen
- `strategies/base.py`: allgemeine Strategievertraege und Gewichtungen
- `strategies/air.py`: Luft-Strategie, strategischer Snapshot und Moduswahl
- `strategies/generic.py`: generische Fallback-Strategie fuer unbekannte Elemente

Abhaengigkeiten:
- Allgemeine Module duerfen `core.models` und Engine-Oberflaechen verwenden.
- Allgemeine Module importieren keine konkreten Luftkarten.
- Die zentrale KI orchestriert ueber Komposition; aktive Luft-Logik laeuft ueber Komponenten statt ueber Mixin-MRO.
- `core.ai_logic` ist nur noch eine Kompatibilitaetsfassade.

Typische Erweiterungen:
- Neue Luftkarte: zuerst `turn_planner.py`, `effect_evaluator_component.py`, `assessment_component.py` oder `reaction_planner.py` waehlen, dann den zugehoerigen Regressionstest ergaenzen.
- Neue allgemeine Mechanik: zuerst in `common.py` oder einem neuen allgemeinen KI-Modul modellieren.
- Neues Element: Strategie in `strategy_registry.py` registrieren und elementeigene Planungs-/Bewertungsmodule daneben kapseln.
