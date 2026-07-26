# Server Design: Scaling Kung Fu Chess to Production Load

This document is a cloud/process-distribution design, not a class/code design - the
same architectural principles apply, but at a very different scale than the current
single-process server in `kungfu_chess/server/`. Target: **100M registered users**,
**10M concurrent players**, games averaging **30-90 seconds**.

Today's server is a single Python `asyncio` process: one in-memory `Matchmaker`
holding every waiting seeker and every active room in plain Python dicts, one
`GameRoom` asyncio task per live game, and one local SQLite file (`kfchess_users.db`)
for accounts. That design is correct for a demo and completely wrong for this scale -
everything below is about *what has to become distributed, and how the pieces talk to
each other*.

## 1. Which servers/processes do we need?

| Role | What it does | Talks to | Protocol |
|---|---|---|---|
| **Gateway / Edge** (stateless, many instances, geo-distributed) | Client's entry point; terminates the WebSocket connection, handles login/register, routes the player to matchmaking or to their room | Client; Accounts service; Matchmaker | WebSocket (client-facing), HTTP/REST (internal) |
| **Matchmaker service** (a handful of instances, not one) | The "bridge between opponents" - owns the shared ELO-seeker queue and the room registry | Gateway; Game-hosting fleet; Redis | HTTP/REST in from Gateway; HTTP/REST (or a queue) to tell a worker to host a room |
| **Game-hosting workers** (by far the most instances) | Run the real-time game loop - today's `GameRoom` logic, unchanged, just made addressable | Clients directly over WebSocket (handed off by Gateway); Accounts service (rating write at game-over) | WebSocket to clients; HTTP/REST to Accounts service |
| **Accounts/Ratings service** (small, few instances) | The *only* thing that talks to the SQL database directly - login, register, rating reads/writes | Postgres/MySQL cluster; called by Gateway and by Game-hosting workers | SQL wire protocol to the DB; HTTP/REST to its callers |
| **Redis** (shared coordination store) | Seeker queue, room registry (`room_id` -> hosting worker), presence/reconnect routing | Matchmaker, Gateway, Game-hosting workers | Redis protocol (RESP) |
| **Orchestrator** (Kubernetes / K3s) | Starts, stops, restarts, and scales the Docker fleet; health-checks workers | Everything (control plane, not the data path) | - |

This directly answers two things the brief asks about: the matchmaker **is** its own
process (not folded into a worker or the gateway), and the "does everyone reach the
same place" question is exactly what the Gateway tier solves - every client's first
hop is one of *many* interchangeable gateway instances, not one fixed address.

## 2. "Open a Docker per game" vs. pooling many games in one process

The lecture's suggested model - **open a Docker when a game starts, close it when the
game ends** - is a real, legitimate pattern (this is how dedicated-game-server fleets
like Agones-on-Kubernetes actually work). It gives clean isolation (one game's crash
can't touch another's) and simple, natural autoscaling (just ask the orchestrator for
more pods when the queue grows).

The real cost is **container cold-start latency**: booting a brand-new container from
scratch for every match is a meaningful chunk of a 30-90 second game. The fix is a
**warm pool** - the orchestrator keeps some idle, already-started containers on
standby; "opening a Docker" for a game means *assigning* one from the pool, not
booting one from zero. That keeps the lecture's mental model (start game -> get a
Docker; end game -> release it) without paying the cold-start cost.

The alternative - today's actual code's model, many `GameRoom`s ticking as asyncio
tasks inside one long-lived process - is also valid. Both are a density/isolation
trade-off, and either way, **the same capacity math below decides how many
processes/containers you need.**

## 3. How many games fit in one process? (the 4GB constraint)

**Memory**: one active game's Python-side footprint (board, pieces, rule engine,
arbiter, move-log/score observers, plus two socket buffers) is roughly 0.5-1MB,
generously rounded. A 4GB process, leaving headroom for the interpreter itself and a
safety margin, could in principle hold on the order of a couple thousand such games by
memory alone.

**But CPU - not memory - is the tighter bound in practice.** One Python process shares
one CPU core's worth of execution (the GIL). Every active game broadcasts a board
snapshot 15 times a second, and that snapshot is real work to serialize (measured
directly from this codebase: **~5.6KB of JSON per snapshot** - see the traffic
calculation in section 5). JSON-encoding that 15x/sec, multiplied across however many
games share one process, adds up well before memory does. The honest answer is: the
practical games-per-process number is an empirical tuning question to benchmark, not
a clean formula - landing somewhere in the low hundreds to low thousands depending on
tuning. The point to take away is that **the 4GB figure alone is not the binding
constraint - CPU is**, so the design is "many worker processes, ideally about one per
CPU core, each capped by measured throughput" rather than "one huge 4GB process."

At 10M concurrent players (5M concurrent games), even an optimistic 1,000
games/worker means **5,000 game-hosting worker processes** running at once, globally,
simultaneously - which is exactly the scale this whole design is for.

## 4. Question 1 - a DB for 100M registered users; is SQLite enough?

**No** - and not because of row count. 100M account rows (username, salt, password
hash, rating) is on the order of tens of GB, trivial for any relational database.
The actual problem is architectural: SQLite is a **single local file with one
writer and no network protocol**. It cannot be safely shared across many separate
worker/Docker processes running on many different machines - there's no way for a
game-hosting worker in one datacenter to reach a SQLite file sitting on disk in
another, and even on one machine, concurrent writers contend for the same file lock.
It also has no built-in replication or failover.

**Recommendation**: a replicated relational database (PostgreSQL or MySQL), reachable
**only** through the Accounts service from section 1 - never directly from thousands
of ephemeral game-hosting workers. That bounds the number of live DB connections to a
small, controlled set regardless of how large the worker fleet grows, and keeps the
one piece of data that genuinely needs strong consistency (unique usernames, correct
password checks) behind one well-defined choke point.

## 5. Question 2 - 10M concurrent players, routing, "everyone plays everyone", any room from anywhere

**One server is nowhere close to enough.** The answer is the catalog in section 1: a
shared Redis-backed queue and room registry decouple *"who's looking for a match /
which worker hosts which room"* (global, must be visible from everywhere) from *"the
real-time simulation itself"* (local to one worker). Two players who land on two
different Gateway instances can still be paired, because the seeker queue is shared,
not held in one process's memory the way today's `Matchmaker._waiting` dict is. "Join
Room" from anywhere resolves through the same shared room registry to whichever
worker actually hosts that room.

**Failure modes** (explicitly required by the brief):

- **A game-hosting worker/Docker dies mid-game** - both clients lose their socket at
  the same instant. Handle it like the existing disconnect-grace mechanism
  (`game_room.py`'s `handle_disconnect` / reconnect grace period already in this
  codebase), except now the *shared* presence store - not one process's local dict -
  has to notice the whole worker is gone (via the orchestrator's health-check).
  Given a game only lasts 30-90 seconds, the honest, simplest answer is: let the game
  end/fail gracefully and let both players re-queue, rather than engineering full
  mid-game state replication for such a short-lived match.
- **A matchmaker instance dies** - no data is lost, because the seeker queue and room
  registry live in Redis, not in that instance's own memory. The orchestrator
  restarts it, and it resumes serving the same shared queue immediately.
- **Redis dies** - the most serious failure, since everything above depends on it.
  Mitigate with Redis replication/clustering (it's built for this). Worth noting
  explicitly: already-running games are **not** affected by a Redis outage - they only
  need their own two sockets - only *new* matchmaking and room-joins pause
  fleet-wide until it recovers.
- **The Accounts DB dies** - new logins/registrations fail, but already-running games
  are unaffected until their game-over rating write, which should be buffered/retried
  (a small outbox) rather than silently lost. Mitigate with a replicated,
  multi-availability-zone DB setup with automatic failover.

## 6. Question 3 - network traffic for one active player (~1 move every 2 seconds)

Client -> server per move is tiny: a click message is about 40-60 bytes of JSON
(`{"type": "select_or_move", "row": r, "col": c}`) - even at one every couple of
seconds, that's negligible.

The real cost is the **server -> client state broadcast**. Today's implementation
resends the *entire* board as JSON at a fixed 15 times/second, regardless of whether
anything actually changed. Measured directly against the real running code (a full
starting-position board, serialized exactly the way `game_room.py` sends it):

```
one StateMessage snapshot  ≈ 5.6 KB (JSON)
broadcast rate              = 15/sec
downstream per player       ≈ 5.6 KB × 15 ≈ 84 KB/s
```

That's roughly the same order of magnitude as a modest video call (~1-2 Mbps ≈
125-250 KB/s) - **per player** - for a game whose actual information content is one
integer move roughly every two seconds. **This is a lot**, disproportionately so
relative to how little actually changes each second, precisely because the current
design re-sends the whole board at a fixed high frequency instead of only what
changed.

At the target scale:

```
10,000,000 concurrent players × 84 KB/s ≈ 840,000,000 KB/s
                                        ≈ 840 GB/s
                                        ≈ 6.7 Tbps of egress, just for state broadcasts
```

That number is the single biggest optimization target in this whole design: lower the
broadcast rate, send binary deltas (only the pieces that actually changed) instead of
a full snapshot every tick, and switch from JSON to a compact binary encoding
(protobuf/msgpack) to shrink the per-message payload well below 5.6KB.

## 7. Question 4 - games last 30-90 seconds; what does that mean for Docker roles?

5,000,000 concurrent games averaging ~60 seconds each implies roughly:

```
5,000,000 games / 60s ≈ 83,000 new games starting - and ending - every second, globally
```

That's continuous churn, not a one-time setup cost, and it has three concrete
consequences for the roles above:

- **Matchmaking tier**: must sustain ~83,000 match-and-create decisions per second,
  continuously, forever - which favors many small, horizontally-sharded matchmaker
  instances (partitioned by rating band and/or region) over one central matchmaker
  like today's single `Matchmaker` class.
- **Game-hosting tier**: reinforces section 2's warm-pool conclusion - at this churn
  rate, cold-starting a container per match would be untenable; rooms need to be cheap
  to spin up and tear down, whether that's "assign from a warm pool" or "start one
  more asyncio task inside an already-running worker."
- **Accounts service**: sees a matching ~83,000 rating-update writes per second
  sustained, globally - reinforcing section 4's answer that this write path needs to
  be behind a dedicated, horizontally-scalable service, not a single SQLite file.

One upside worth naming: because games are so short-lived, the system **rebalances
fast** - an overloaded game-hosting worker fully drains within about a minute as its
current games finish, so autoscaling can be far more responsive than it would be for
a genre with hour-long matches.

## 8. Why this meets the requirements

1. **100M registered users** - a replicated Postgres/MySQL cluster behind a single
   Accounts service (section 4) comfortably handles the data volume; SQLite is ruled
   out for architectural reasons, not size.
2. **10M concurrent players, routing, shared rooms, role division** - a Gateway tier,
   a Redis-backed Matchmaker tier, and a large Game-hosting worker fleet (sections 1,
   2, 3, 5) with explicit failure handling for every tier.
3. **Network traffic at ~1 move/2s** - measured directly from the real code:
   ~84 KB/s/player, ~6.7 Tbps fleet-wide - identified as large and disproportionate to
   the actual information rate, with concrete fixes (section 6).
4. **30-90 second games** - ~83,000 games/sec of churn drives the warm-pool design,
   sharded matchmaking, and a dedicated write-scalable ratings path (section 7).
