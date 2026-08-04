# Luft-KI

Zweck: Luft-spezifische Planung, Bewertung und Reaktionslogik.

Dateien:
- `planning.py`: Ressourcen- und Main-Phase-Entscheidungen
- `effects.py`: Vergleich von Luftkarten mit und ohne Ausspielen
- `assessment.py`: Kartenwert, Keep-Wert, Angriffs- und Schadensbewertung
- `reactions.py`: Reaktionsfenster, Zielwahl, Timing sensibler Luftzauber
- `handlers.py`: Luft-Zauber- und Ritual-Handler-Registry
- `creature_handlers.py`: Luft-Kreaturen-Guidelines und Keep-Handler

Abhaengigkeiten:
- nutzt allgemeine KI-Helfer aus `core.ai.common`
- importiert keine anderen Elementstrategien
- bleibt über `core.ai.simple_ai.SimpleAI` angebunden

Typische Erweiterungen:
- neue Luftkarte: zuerst passendes Modul wählen, dann Regression in `tests/test_ai_confirmation.py`
- neue allgemeine Mechanik: erst in ein allgemeines KI-Modul ziehen, dann hier nur Luft-Gewichtung ergaenzen
- kartenspezifische Luftzauber liegen in `handlers.py`
- kartenspezifische Luftkreaturen liegen in `creature_handlers.py`
