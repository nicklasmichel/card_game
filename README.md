# GODAO

**Game of Decisions and Odds** is a tactical card game in which deterministic
planning meets probabilistic dice combat.

## Start

```powershell
python scripts/run_game.py
```

The start screen offers three modes:

- **PvE vs AI** starts the existing local game.
- **Host PvP** asks for your player name, opens TCP port `47621`, and waits for one friend.
- **Join PvP** asks for your player name and connects to `IP:port` (the port defaults to `47621`).

For a Hamachi match, both players should use the same repository revision and
start their own GODAO instance. The host shares their Hamachi IPv4 address; the
guest enters it in the Join screen, for example `25.10.20.30:47621`. If Windows
Firewall asks, allow Python on the relevant private network. The host chooses
the starting player after the guest has connected.

If the connection drops during a match, GODAO pauses gameplay on both sides and
the guest reconnects automatically. The running guest instance keeps its reserved
player slot; a different client cannot take over an active match. Confirmed public
actions and combat results are synchronized in the gameplay log, while private
hands and tentative attacker/blocker choices remain hidden.

## Creature builder

Every new creature receives exactly one free primary ability: **Flying**,
**Vigilance**, or **Trample**. **Haste** is an independent optional upgrade and
costs one resource. The remaining ready resources are distributed across
Attack, Defense, Damage, and Life, so a five-resource creature has either five
stat points or four stat points plus Haste. A creature with Haste can therefore
have two abilities: Haste and its free primary ability.

## Tests

```powershell
python -m unittest discover
```

## AI soak test

Run deterministic AI-vs-AI games with legality checks, state invariants, and a
30-second watchdog for every AI decision:

```powershell
python scripts/run_soak.py --games 100
```

Use `--starting-life 15` to test a life-total variant without changing the
normal game configuration.

The summary reports average, P95, P99, and worst AI decision times. Each game
runs in an isolated process by default, so a stuck calculation is terminated
and reported instead of hanging the complete run. Add `--json soak-report.json`
to save all per-game and per-decision measurements, including phase/action
breakdowns, search work counters, board snapshots for slow decisions, and the
distribution of actual creature builds. The build report separates primary
abilities, paid Haste, immediate Haste attacks, defensive Haste coverage, and
average stat allocation. The snapshot threshold can be changed with
`--slow-snapshot-ms`.

Completed games also append every created builder creature to
`stats/data/builder_creature_build_results.csv`. Each row contains its stats,
free primary ability, paid Haste choice, stat cost, and total resource cost.

## Playtest report

After a PvE test, including an aborted game, analyze the latest logged match:

```powershell
python scripts/analyze_playtest.py --json stats/data/latest_playtest.json
```

The report compares player and AI builds, paid Haste rates, primary abilities,
resource-cost consistency, and AI decision times. Structured game markers keep
the latest match separate from older log entries.
