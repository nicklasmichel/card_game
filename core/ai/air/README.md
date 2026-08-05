# Luft-KI

Zweck: Luft-spezifische Planung, Bewertung und Reaktionslogik.

Dateien:
- `planning.py`: Ressourcen-, Hauptphasen- und Turn-Plan-Steuerung
- `effects.py`: Vergleich von Luftkarten mit und ohne Ausspielen
- `assessment.py`: Kartenwert, Keep-Wert, Angriffs- und Schadensbewertung
- `reactions.py`: Reaktionsfenster, Zielwahl, Timing sensibler Luftzauber
- `handlers.py`: Luft-Zauber- und Ritual-Handler-Registry
- `creature_handlers.py`: Luft-Kreaturen-Guidelines und Keep-Handler
- `core/ai/plans.py`: allgemeines typisiertes Planmodell
- `core/ai/candidates.py`: typisierte Zugkandidaten und projizierte Planungszustaende

Abhaengigkeiten:
- nutzt allgemeine KI-Helfer aus `core.ai.common`
- importiert keine anderen Elementstrategien
- bleibt ueber `core.ai.simple_ai.SimpleAI` angebunden

Planarchitektur:
- der aktive Plan liegt auf der AI-Instanz als `TurnPlan`
- `planning.py` erzeugt mehrere begrenzte `TurnPlanCandidate`, filtert dominierte Varianten und aktiviert den besten Plan
- jeder Luft-Plan traegt einen strategischen Modus, ein primaeres Ziel, Reason Codes und kompakte Snapshot-Metriken
- `prepare_ai_turn_action()` fragt weiterhin nur die naechste Aktion ab
- vor weiteren KI-Aktionen wird der aktive Plan validiert
- nach erfolgreicher Ausfuehrung markiert die Engine den aktuellen Planschritt als erledigt
- bei falschem Zug, fehlender Karte, fehlendem Ziel oder unerwarteter Phase wird der Plan verworfen und spaeter neu aufgebaut
- bei geaenderter strategischer Lage wird ebenfalls neu geplant
- Ressourcenreservierungen fuer spaetere Kampfzauber liegen als Planabsicht im `TurnPlan`
- das Planmodell ist allgemein gehalten und kann spaeter auch von anderen Elementen genutzt werden

Kandidatenplanung:
- `PlanningState` beschreibt den leichten projizierten Zustand fuer die aktuelle Zugplanung
- `MainPhaseSequenceCandidate` trennt Hauptphase 1 und Hauptphase 2
- `AttackCandidate` traegt Angreifergruppe, erwarteten Schaden, Verluste und Gegenzugrisiko
- `TurnPlanCandidate` verbindet Main 1, Kampf, Main 2, Reservierungen und Bewertung
- Ressourcenvarianten pruefen 0, 1 oder 2 Ressourcenspiele mit unterschiedlichem Timing vor oder nach dem Kampf
- Angriffsgruppen werden heuristisch erzeugt und begrenzt, nicht vollstaendig durchsucht
- bedingte Reaktionen bleiben `ReactionIntent` und werden nur als Planabsicht gespeichert
- ein grober Gegenzug wird nur aus oeffentlichen Informationen abgeschaetzt
- der beste Kandidat wird deterministisch in `TurnPlan` umgewandelt

Strategieebene:
- allgemeines Interface in `core/ai/strategies/base.py`
- Luftstrategie in `core/ai/strategies/air.py`
- `AirStrategy` erzeugt einen oeffentlichen Lagebericht, waehlt genau einen Modus und liefert ein kleines Gewichtungsprofil
- Modi: `LETHAL`, `PRESSURE`, `BUILD_SWARM`, `RELOAD`, `RECOVER`, `STABILIZE`
- `planning.py`, `assessment.py`, `effects.py` und `reactions.py` nutzen diese Gewichte, behalten aber ihre bestehende lokale Logik
- weitere Elemente koennen dieselbe Schnittstelle spaeter mit eigener Strategy-Klasse verwenden

Typische Erweiterungen:
- neue Luftkarte: zuerst passendes Modul waehlen, dann Regression in `tests/test_ai_confirmation.py`
- neue allgemeine Mechanik: erst in ein allgemeines KI-Modul ziehen, dann hier nur Luft-Gewichtung ergaenzen
- kartenspezifische Luftzauber liegen in `handlers.py`
- kartenspezifische Luftkreaturen liegen in `creature_handlers.py`
