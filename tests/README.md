# Teststruktur

Aktuelle Schwerpunkte:
- `test_resource_and_recycle.py`: Ressourcenphase, Recycle, Ressourcenwahl
- `test_spells.py`: Regeltests fuer Zauber, Timingfenster, Aufloesung
- `test_fire_spells_rework.py`: neues Feuer-Timing, Kampfzauberfenster und Feuerzauber
- `test_ai_confirmation.py`: KI-Regressionen und konkrete Luftentscheidungen
- `helpers.py`: generische Engine-Testhilfe
- `ai_scenario_builder.py`: kompakter Szenarioaufbau fuer neue KI-Regressionen

Typische Aenderungen:
- Neue Luftzauberregel: `test_spells.py`
- Neues Feuer-Timing oder Feuerzauber-Rework: `test_fire_spells_rework.py`
- Neue Luft-KI-Heuristik: `test_ai_confirmation.py`
- Ressourcen- oder Recycle-Regel: `test_resource_and_recycle.py`
