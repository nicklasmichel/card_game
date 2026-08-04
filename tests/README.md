# Teststruktur

Aktuelle Schwerpunkte:
- `test_resource_and_recycle.py`: Ressourcenphase, Recycle, Ressourcenwahl
- `test_spells.py`: Regeltests fuer Zauber, Timingfenster, Aufloesung
- `test_ai_confirmation.py`: KI-Regressionen und konkrete Luftentscheidungen
- `helpers.py`: generische Engine-Testhilfe
- `ai_scenario_builder.py`: kompakter Szenarioaufbau fuer neue KI-Regressionen

Typische Aenderungen:
- Neue Luftzauberregel: `test_spells.py`
- Neue Luft-KI-Heuristik: `test_ai_confirmation.py`
- Ressourcen- oder Recycle-Regel: `test_resource_and_recycle.py`
