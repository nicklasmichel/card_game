# Teststruktur

Aktuelle Schwerpunkte:
- `test_builder_mode.py`: Builder-Runtime, UI-Flow, kostenpflichtiges Haste und Builder-Combat-Regressionen
- `test_builder_debug_logging.py`: Builder-Debug-Ausgabe und Nichtmutation der Planung
- `test_builder_turn_ai.py`: Main-Action-Planung im Builder-Modus
- `test_builder_attack_ai.py`: Angreiferauswahl im Builder-Modus
- `test_builder_block_ai.py`: Blockzuweisung im Builder-Modus
- `test_builder_combat_eval.py`: Builder-Kampfprojektionen und Wahrscheinlichkeiten
- `test_builder_ai.py`: uebergeordnete Builder-KI-Regressionen
- `test_builder_statistics.py`: persistierte Builder-Build- und Haste-Balancewerte
- `test_ai_confirmation.py`: bestaetigte Enemy-KI-Aktionen im Builder-Flow
- `test_game_invariants.py`: zentrale Zustands-, Ressourcen- und Kampfregeln
- `test_soak_runner.py`: Soak-Runner, Zeitmetriken, Build-Verteilungen und Fehlerberichte
- `test_playtest_report.py`: Auswertung der letzten vollstaendigen oder abgebrochenen Testrunde
- `helpers.py`: generische Builder-Testhilfe
- `ai_scenario_builder.py`: kompakter Szenarioaufbau fuer neue Builder-KI-Regressionen

Nicht mehr relevant:
- Deck-/Spell-/Recycle-/Reaction-Tests des alten Normal-Modus werden nicht mehr gepflegt.
