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

Every creature starts at **0 Attack / 0 Defense / 0 Damage / 1 Life**. All ready
resources are then distributed across those four stats; only points above those
base values contribute to the stat cost. No individual stat can be raised above
**5** during creature construction.

Haste is the only ability available while building a creature. It is optional
and does not reduce the stat budget: with five ready resources, all five may be
spent on stats. Afterward, granting Haste permanently removes one resource from
the player. A creature with Haste enters play ready; every other newly built
creature enters tapped. Builder creatures without Haste use the Vigilance
artwork as their default image.

At the beginning of each turn, the active player automatically gains one ready
resource for free, up to the resource cap of **10**. This does not consume the
turn's main action; choosing to add another resource remains a valid main action.

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
distribution of actual creature builds. The build report separates paid Haste,
immediate Haste attacks, defensive Haste coverage, and average stat allocation.
The snapshot threshold can be changed with
`--slow-snapshot-ms`.

## AI profile benchmark

Benchmark the production AI against independent aggressive, defensive,
balanced, and seeded-random policies:

```powershell
python scripts/run_profile_benchmark.py --seeds 5 --workers 4
```

Every seed is played twice with the starting player mirrored. The report tracks
win rate, game length, resource and board curves, attacks and passes, creature
stat allocation, player damage, creature trades, dice expectation versus actual
results, decision timing, and automatic audits for score inversions or missed
guaranteed lethal. JSON and Markdown reports are written to
`stats/data/profile_benchmark_latest.*`.

If only a few games exceed the configured game timeout, retry those exact
profile/seed/start combinations without replaying completed games:

```powershell
python scripts/retry_profile_benchmark_failures.py --game-timeout 300 --workers 2
```

Completed games also append every created builder creature to
`stats/data/builder_creature_build_results.csv`. Each row contains its stats,
paid Haste choice, stat cost, and total resource cost.

## Playtest report

After a PvE test, including an aborted game, analyze the latest logged match:

```powershell
python scripts/analyze_playtest.py --json stats/data/latest_playtest.json
```

The report compares player and AI builds, paid Haste rates, resource-cost
consistency, and AI decision times. Structured game markers keep
the latest match separate from older log entries.
