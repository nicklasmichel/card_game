# AI Architecture

## Oeffentliche Einstiegspunkte

- `core.ai.simple_ai.SimpleAI`
- `core.ai.context.build_ai_context`
- `core.ai_logic` nur als Kompatibilitaetsfassade fuer bestehende Importe

## Verzeichnisstruktur

- `core/ai/common.py`: allgemeine KI-Auswahl, Blocken, Recycle, Wuerfelstrategie
- `core/ai/air/planning.py`: Ressourcen- und Main-Phase-Planung der Luft-KI
- `core/ai/air/effects.py`: kartennahe Effektvergleiche fuer Luft
- `core/ai/air/assessment.py`: Handwert, Kartenwert, Angriffsbewertung, Luft-spezifische Keep-Heuristiken
- `core/ai/air/reactions.py`: Reaktionsfenster, Zauberauswahl, Zielauswahl
- `core/ai/context.py`: kompakter, regelkonformer KI-Kontext ohne verdeckte Informationen
- `core/ai/types.py`: Kandidat-, Plan- und Begruendungstypen

## Entscheidungsablauf

1. Engine ruft `SimpleAI` auf.
2. KI bewertet Ressourcenplan, Main-Phase-Plan, Angriff oder Reaktion.
3. Luft-spezifische Effekte werden in den Luftmodulen verglichen.
4. Nach Kartenziehen, Zufall oder gegnerischer Reaktion darf die KI neu planen.

## Allgemeine Mechanik vs. Elementstrategie vs. Kartenlogik

- Allgemeine Mechanik: Recycle, Blockwahl, Wuerfelstrategie, konservative Fallbacks
- Elementstrategie: Luft priorisiert Tempo, kleine Ressourcenbasis, vierte Handkarte, Fliegend/Schnell
- Kartenlogik: `Aufwind`, `Rueckenwind`, `Sturmformation`, `Turbulenz`, `Ausweichen`, `Windstoss`, `Boeenschub`, `Windrausch`, `Nachwehen`

## Aktionskandidaten und Planbindung

`core.ai.types` definiert kompakte Typen fuer:
- `DecisionReason`
- `ActionCandidate`
- `BoundPlan`

Bestehende Luftplaene bleiben aktuell noch als leichte Dictionaries in `SimpleAI` gebunden, damit das Verhalten stabil bleibt. Die neuen Typen sind die Zieloberflaeche fuer weitere inkrementelle Umstellungen.

## Neue Karte ergaenzen

1. Passende allgemeine Mechanik oder Luftdatei waehlen.
2. Bewertungslogik im passenden Luftmodul ergaenzen.
3. Falls noetig Ziel- oder Reaktionsauswahl in `air/reactions.py` ergaenzen.
4. Regression in `tests/test_ai_confirmation.py` und Regeltest in `tests/test_spells.py` anlegen.

## Neues Element ergaenzen

1. Neues Unterverzeichnis unter `core/ai/` anlegen, z. B. `fire/`.
2. Elementeigene Planungs-, Bewertungs- und Reaktionsmodule dort kapseln.
3. `SimpleAI` um die neue Strategieanbindung erweitern, ohne Luftmodule zu veraendern.

## Wichtigste Tests

- Ressourcen / Recycle: `tests/test_resource_and_recycle.py`
- Zauber / Timing: `tests/test_spells.py`
- KI-Regressionen: `tests/test_ai_confirmation.py`

## Informationsgrenzen der KI

- Keine Kenntnis verdeckter Karten
- Keine Kenntnis zukuenftiger Wuerfelergebnisse
- Bewertung nur aus sichtbarem Spielzustand, Deckstruktur und Wahrscheinlichkeiten
