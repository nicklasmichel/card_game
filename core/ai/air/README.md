# Luft-KI

Zweck: Luft-spezifische Planung, Bewertung und Reaktionslogik.

Dateien:
- `planning.py`: Ressourcen- und Main-Phase-Entscheidungen
- `effects.py`: Vergleich von Luftkarten mit und ohne Ausspielen
- `assessment.py`: Kartenwert, Keep-Wert, Angriffs- und Schadensbewertung
- `reactions.py`: Reaktionsfenster, Zielwahl, Timing sensibler Luftzauber

Abhaengigkeiten:
- nutzt allgemeine KI-Helfer aus `core.ai.common`
- importiert keine anderen Elementstrategien
- bleibt ueber `core.ai.simple_ai.SimpleAI` angebunden

Typische Erweiterungen:
- neue Luftkarte: zuerst passendes Modul waehlen, dann Regression in `tests/test_ai_confirmation.py`
- neue allgemeine Mechanik: erst in ein allgemeines KI-Modul ziehen, dann hier nur Luft-Gewichtung ergaenzen

Hinweis:
- mehrere `template_id`s verwenden noch alte Luft-Kartennamen; in Tests und KI-Texten die aktuellen Anzeigenamen verwenden, die IDs aber technisch unveraendert lassen
