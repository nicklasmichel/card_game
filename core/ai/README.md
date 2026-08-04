# KI-Module

Zweck: Aufteilung der bisherigen `core/ai_logic.py` in kleine, stabile Bereiche.

Oeffentliche Einstiegspunkte:
- `core.ai.simple_ai.SimpleAI`
- `core.ai.context.build_ai_context`
- `core.ai.types.ActionCandidate`

Wichtige Dateien:
- `common.py`: allgemeine Auswahlregeln, Blocken, Recycle, Wuerfelstrategie
- `air/planning.py`: Ressourcen- und Main-Phase-Planung der Luft-KI
- `air/effects.py`: Luft-spezifische Effektbewertungen und Vergleichsplaene
- `air/assessment.py`: Hand-/Kartenbewertung, Angriffsbewertung, Luft-spezifische Keep-Werte
- `air/reactions.py`: Reaktionsauswahl, Zielwahl, Zauberauswahl in Fenstern

Abhaengigkeiten:
- Diese Module duerfen `core.models` und Engine-Oberflaechen verwenden.
- Allgemeine Module importieren keine konkreten Luftkarten.
- `core.ai_logic` ist nur noch eine Kompatibilitaetsfassade.

Typische Erweiterungen:
- Neue Luftkarte: zuerst passendes Luftmodul waehlen, dann zugehoerigen Regressionstest ergaenzen.
- Neue allgemeine Mechanik: zuerst in `common.py` oder einem neuen allgemeinen KI-Modul modellieren.
- Neues Element: eigenes Unterverzeichnis neben `air/` anlegen, ohne Luftmodule zu veraendern.
