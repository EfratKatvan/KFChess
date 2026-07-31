# Kung Fu Chess

A real-time chess variant: unlike standard chess, there are no turns -
both players can move simultaneously, and a move takes a moment to
travel across the board (with a cooldown afterward) rather than
resolving instantly. Includes a networked client/server mode (login,
ELO-based matchmaking, named rooms, spectating) and a local
text-command mode for scripted test boards.

## Requirements

- Python 3.11+
- `pip install -r requirements.txt` (installs `opencv-python`, `websockets`, `redis`, `aiohttp`)
- Redis running on `localhost:6379` - `docker-compose up -d` (starts just
  Redis; everything else below is a plain Python process, not a container)

## Running a two-player game locally

Today's server is split into four processes (Server_Design.md's Stages
0-4a), each in its own terminal, started in this order from the project
root:

**1. Redis** (once):

```
docker-compose up -d
```

**2. Accounts/Ratings API Service** (once):

```
python -m kungfu_chess.server.accounts_service
```

Listens on `http://localhost:8766`. Creates `kfchess_users.db` (SQLite,
usernames/password hashes/ratings) in the working directory on first
run - the only process that ever touches it directly.

**3. Game Shard** (once):

```
python shard.py
```

Listens on `ws://localhost:8767` - reached only by the WS Gateway below
(a relay connection per seat), never directly by a client. This is
where `GameRoom`s actually live and tick (Server_Design.md Stage 4a).

**4. WS Gateway** (once):

```
python server.py
```

Listens on `ws://localhost:8765` - the one address a client ever
connects to. Handles login/matchmaking directly, and relays gameplay
traffic to/from the Game Shard once a match/room is underway.

**5. Start a client, once per player** (run this command again in a
second terminal for the second player):

```
python app.py
```

The game window opens right away - no terminal prompts. First pick a
piece set (Pieces 1/2/3), then log in or register: type a username,
Tab (or click) to the password field, type a password, and click
**LOGIN** (fails if the username doesn't exist yet, or the password is
wrong) or **REGISTER** (fails if the username is already taken). A
rejected attempt keeps the typed username and clears the password so
you can just retry, no restart needed. From the lobby:

- **Play** — ELO-ranged matchmaking against whoever else clicks Play
  within ~100 rating points; a **Back** button appears while waiting.
- **Create Room** / **Join Room** — type a room name to start or join
  a specific game; a third player joining the same room spectates.

During a match: right-click a piece to jump it (a non-standard extra
move), **Resign** forfeits on demand, and once the game ends **New
Game** offers a rematch or **Back to Lobby** returns you there.

## Running the local text-command mode

`main.py` reads a board layout plus a scripted list of moves from
stdin (no networking, no window) — used by the integration tests
under `tests/integration/`:

```
python main.py < path/to/script.txt
```

## Running the tests

Requires Redis running on `localhost:6379` (`docker-compose up -d`) -
the server-side test suite talks to a real Redis instance, not a mock
(same for the real Accounts Service/Game Shard/WS Gateway instances
several tests spin up on background threads - see `tests/unit/conftest.py`).

```
pip install pytest pytest-cov   # if not already installed
python -m pytest
```

With coverage:

```
python -m pytest --cov=kungfu_chess --cov-report=term-missing
```

## Project layout

- `kungfu_chess/model/`, `rules/`, `realtime/`, `engine/` — the game
  logic: board/piece representation, per-piece movement rules,
  real-time motion/cooldown/collision handling, and the
  `GameEngine` service that ties them together.
- `kungfu_chess/events/` — a small publish/subscribe `Bus`, and the
  concrete `MoveLogObserver`/`ScoreObserver` listeners `GameEngine`
  publishes move/capture events to.
- `kungfu_chess/server/` — the WebSocket server: login/registration
  (`accounts.py`, backed by `accounts_db.py`), matchmaking and room
  management (`matchmaker.py`, `rooms.py`), and one `GameRoom` per
  live match (authoritative rules, real-time tick loop, broadcasts).
- `kungfu_chess/client/` — the networked client's non-visual layers:
  `client_state.py` (what the client knows), `network_transport.py`
  (the WebSocket connection), `input_controller.py` (clicks/keys ->
  outgoing messages), `sound.py` (select/move/capture/invalid/
  game-start/game-over sound effects).
- `kungfu_chess/view/` — rendering: `renderer.py` (board/pieces/side
  panels), `network_presentation.py` (every other screen: lobby, room
  dialogs, top banner), `network_client_view.py` (wires it all
  together into the actual window/render loop).
- `tests/unit/`, `tests/integration/` — the test suite (`pytest`).
