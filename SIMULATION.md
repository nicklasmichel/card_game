# KI-Matchup-Simulation

Der Simulationspfad misst Luft gegen Feuer reproduzierbar. Er aendert keine Kartenwerte und keine KI-Gewichte.

## Starten

Ein einfacher Batch:

```bash
python tools/simulation/run_matchup.py --deck-a air --deck-b fire --games 200 --seed-start 200000
```

Mit JSON-Ausgabe:

```bash
python tools/simulation/run_matchup.py --deck-a air --deck-b fire --games 200 --seed-start 200000 --json-out simulation/baseline_air_fire.json
```

Mit festem Startspieler:

```bash
python tools/simulation/run_matchup.py --games 50 --seed-start 300000 --start-player 0
```

`start-player 0` bedeutet, dass `deck-a` beginnt. `start-player 1` bedeutet, dass `deck-b` beginnt. Ohne Vorgabe wird der Startspieler pro Partie alterniert.

## Seeds

Die Simulation verwendet genau die uebergebenen Seeds. Mit demselben:

- Seed
- Deckpaar
- Startspieler
- Codezustand

soll dieselbe Partie wieder entstehen.

## Einzelne Partie reproduzieren

Eine einzelne Partie:

```bash
python tools/simulation/run_matchup.py --games 1 --seed-start 255163705242 --start-player 1 --json-out simulation/replay_255163705242.json
```

## Decks und Partiezahl

Decks werden ueber `--deck-a` und `--deck-b` gesetzt. Die Partiezahl kommt ueber `--games`. Die Seed-Reihe startet bei `--seed-start` und laeuft dann fortlaufend.

## JSON-Bericht

Der JSON-Bericht enthaelt:

- Batch-Konfiguration
- Partiemetriken
- Spielertelemetrie
- Aktionslisten
- Modi und Planrevisionen
- optionale Replays

## Neue Metrik ergaenzen

Die Telemetrie liegt in `simulation/telemetry.py`. Die Erfassung haengt an den echten Spielereignissen in `simulation/engine.py`, zum Beispiel:

- `draw_card_for_player`
- `resolve_creature_play`
- `commit_spell_cast`
- `confirm_attackers`
- `resolve_pending_direct_attack_after_reaction`

Neue Metriken sollten dort an ein konkretes, regelbasiertes Ereignis gehaengt werden. Nicht an freie Interpretationen eines Logs.

## Technischer Fehler vs. Balanceauffaelligkeit

Technische Fehler:

- Seed nicht reproduzierbar
- festhaengende Phase
- ungueltige Ziel- oder Stack-Abwicklung
- Max-Turn- oder Max-Action-Abbruch

Balance- oder KI-Auffaelligkeiten:

- ein Deck gewinnt zu oft
- ein Modus wird zu selten benutzt
- Karten bleiben zu haeufig auf der Hand
- eine offensichtliche Aktion wird wiederholt verpasst

Die Simulation soll diese Auffaelligkeiten sichtbar machen. Sie soll sie in diesem Block nicht automatisch umgewichten.
