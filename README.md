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

## Tests

```powershell
python -m unittest discover
```
