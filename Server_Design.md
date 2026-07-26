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

## 0. The pattern the code already follows

It's worth naming this before scaling anything: `kungfu_chess/events/bus.py`'s `Bus`
is already a small publish/subscribe system - `GameEngine` publishes move/capture
events onto it, and `MoveLogObserver`/`ScoreObserver` subscribe without either side
knowing about the other directly. That's exactly the shape a distributed system
needs: a publisher that doesn't know who's listening, and subscribers that don't know
where the publisher lives. Everything below is that same pattern, stretched across
process and machine boundaries - not a foreign concept bolted onto the project.

## 1. Which servers/processes do we need?

| Role | What it does | Talks to | Protocol | Scales on |
|---|---|---|---|---|
| **Gateway / Edge** (stateless, many, geo-distributed) | Client's entry point; terminates the WebSocket, handles login/register, routes the player onward | Client; Accounts service; Matchmaker; a Game-hosting worker once matched | WebSocket (client-facing); HTTP/REST (internal) | Open connections |
| **Matchmaker service** (a handful of instances, not one) | The "bridge between opponents" - owns the shared ELO-seeker queue and the room registry | Gateway; Game-hosting fleet; Redis | HTTP/REST in from Gateway; publishes a low-volume "game-created" event | Queue depth |
| **Game-hosting workers** (by far the most instances) | Run the real-time game loop - today's `GameRoom` logic, unchanged, just made addressable | Clients directly over WebSocket (handed off by Gateway); Accounts service (rating write at game-over) | WebSocket to clients; HTTP/REST to Accounts service | Active-room count / CPU |
| **Accounts/Ratings service** (small, few instances) | The *only* thing that talks to the SQL database directly - login, register, rating reads/writes | Postgres/MySQL cluster; called by Gateway and by Game-hosting workers | SQL wire protocol to the DB; HTTP/REST to its callers | Request rate |
| **Redis** (shared coordination store) | Seeker queue, room-ownership registry (`room_id` -> hosting worker, leased - see section 3), presence/reconnect routing | Matchmaker, Gateway, Game-hosting workers | Redis protocol (RESP) | Lookup/lease rate |
| **Control-plane broker** (NATS/Kafka) | Low-volume events: game-created, game-finished, presence changes | Matchmaker, Game-hosting workers, Persistence workers | Broker's own protocol | Event rate (low volume) |
| **Orchestrator** (Kubernetes / K3s) | Starts, stops, restarts, and scales the Docker fleet; health-checks workers | Everything (control plane, not the data path) | - | - |

This directly answers two things the brief asks about: the matchmaker **is** its own
process (not folded into a worker or the gateway), and "does everyone reach the same
place" is exactly what the Gateway tier solves - every client's first hop is one of
*many* interchangeable gateway instances, not one fixed address.

## 2. Two kinds of traffic need two kinds of transport

Not everything above should share one pipe. Two very different traffic shapes exist:

- **Control plane** - low volume, latency-tolerant: matchmaking decisions, room
  creation, game-finished notifications, presence changes. A real message broker
  (NATS/Kafka) suits this well - the decoupling is valuable (a Gateway publishing
  "player wants a match" doesn't need to know in advance which worker will end up
  hosting it), and the volume is low enough that broker overhead is a non-issue.
- **Data plane** - high volume, latency-sensitive: the live gameplay stream itself,
  up to 15 broadcasts/sec *per active room* (today's `BROADCAST_INTERVAL_SECONDS`).
  This must be a **direct stream** from Gateway to the *specific* Game-hosting worker
  that owns the room (resolved once via the room registry), not routed through the
  shared broker on every tick. Pushing the full gameplay volume (section 8: multiple
  Tbps at this scale, before optimization) through a general-purpose broker would
  make the broker itself the bottleneck.

## 3. Room ownership: the gap a registry alone doesn't close

A `room_id -> worker` mapping in Redis is necessary but not sufficient. It tells a
new joiner *where to look*; it does not by itself guarantee that only **one** worker
ever believes it is allowed to advance a given room's simulation. Without an explicit
ownership mechanism, a rebalance or an unclean failover could leave two Game-hosting
workers both accepting moves for the same room - two disagreeing versions of the same
game.

The fix: room assignment is a **lease**, not just a registry entry -
`SET room:<id>:owner <worker-id> NX PX 5000`, renewed by heartbeat while the worker
actually holds the room, and simply left to expire on crash (no clean shutdown
required for correctness). A replacement worker can only take over once the lease has
actually expired, never by overwriting a live one. This is the distributed-scale
counterpart of what `game_room.py`'s `handle_disconnect`/`try_reconnect` and
`DISCONNECT_GRACE_SECONDS` already do for a *single* dropped socket within one
process - the lease is the same idea (a bounded grace period before someone else can
claim the seat), just applied to "which worker owns this room" instead of "which
connection owns this color."

## 4. "Open a Docker per game" vs. pooling many games in one process

**Open a Docker when a game starts, close it when the game ends** is a real,
legitimate pattern (this is how dedicated-game-server fleets like Agones-on-Kubernetes
actually work). It gives clean isolation (one game's crash can't touch another's) and
simple, natural autoscaling (ask the orchestrator for more pods as the queue grows).

The real cost is **container cold-start latency**: booting a brand-new container from
scratch for every match is a meaningful chunk of a 30-90 second game, and (section 9)
happens roughly 83,000 times a second at target scale - far too often to cold-start.
The fix is a **warm pool** - the orchestrator keeps some idle, already-started
containers on standby; "opening a Docker" for a game means *assigning* one from the
pool, not booting one from zero.

The alternative - today's actual code's model, many `GameRoom`s ticking as asyncio
tasks inside one long-lived process - is also valid, and is in fact what a
Game-hosting *worker* (section 1) does internally: one process, one Docker container,
many concurrent rooms. Both models are a density/isolation trade-off; either way, the
capacity math below decides how many worker processes you actually need.

## 5. How many games fit in one process? (the 4GB constraint)

**Memory**: one active game's Python-side footprint (board, pieces, rule engine,
arbiter, move-log/score observers, plus two socket buffers) is roughly 0.5-1MB,
generously rounded. A 4GB process, leaving headroom for the interpreter itself and a
safety margin, could in principle hold on the order of a couple thousand such games by
memory alone.

**But CPU - not memory - is the tighter bound in practice.** One Python process
shares one CPU core's worth of execution (the GIL): `GameRoom._run` is a sequential
tick loop, and a process doesn't get faster by giving it more cores, only by running
more copies of it. Every active game also broadcasts a board snapshot 15 times a
second, and that snapshot is real work to serialize (measured directly from this
codebase: **~5.6KB of JSON per snapshot** - see section 8). JSON-encoding that
15x/sec, multiplied across however many games share one process, adds up well before
memory does. The honest answer is that the practical games-per-process number is an
empirical tuning question to benchmark, not a clean formula - landing somewhere in the
low hundreds to low thousands depending on tuning. The point to take away: **the 4GB
figure alone is not the binding constraint - CPU is**, so the design is "many worker
processes, ideally about one per CPU core, each capped by measured throughput," not
"one huge 4GB process."

By Little's Law, 10M concurrent players at 2 players/game means **5M concurrent
games**; even an optimistic 1,000 games/worker means **5,000 Game-hosting worker
processes** running at once, globally, simultaneously.

## 6. Question 1 - a DB for 100M registered users; is SQLite enough?

**No** - and not because of row count. 100M account rows (username, salt, password
hash, rating) is on the order of tens of GB, trivial for any relational database. The
actual problem is architectural:

- SQLite is a **single local file with one writer and no network protocol** - it
  cannot be safely shared across many separate worker/Docker processes running on
  many different machines. There's no way for a Game-hosting worker in one
  datacenter to reach a SQLite file sitting on disk in another, and even on one
  machine, concurrent writers contend for the same file.
- It has **no built-in replication, sharding, or failover** - one crash takes the
  whole dataset down.

**Recommendation**: a replicated relational database (PostgreSQL or MySQL), reachable
**only** through the Accounts service from section 1 - never directly from thousands
of ephemeral Game-hosting workers. That bounds the number of live DB connections to a
small, controlled set regardless of how large the worker fleet grows, and keeps the
one piece of data that genuinely needs strong consistency (unique usernames, correct
password checks, atomic rating updates) behind one well-defined choke point. Shard by
`user_id` hash (e.g. Citus/Vitess) if write throughput - not storage - ever becomes the
limit; section 9's ~83,000 rating-writes/sec is exactly the number that would force
that decision. Presence, the seeker queue, and the room-ownership lease (section 3)
deliberately do **not** live here - that ephemeral, extremely high-churn data belongs
in Redis, not a relational DB.

## 7. Question 2 - 10M concurrent players: routing, "everyone plays everyone", any room from anywhere

**One server is nowhere close to enough**, for two independent reasons: no single
process can hold 10M sockets, and - separately - no single Python process can run
5M rooms' worth of tick computation on one core regardless of socket count.

"Everyone can play with everyone, and anyone can join any room" works because no
client ever needs to know which physical machine anything lives on:

1. A player connects to whichever Gateway is nearest (GeoDNS/global load balancer).
   The Gateway computes no game logic - it only holds the socket and forwards traffic.
2. **Play** -> Gateway forwards to the Matchmaker, which sees every waiting player
   *globally* (the shared Redis-backed queue - section 1), not just players on this
   one Gateway. A player on a US gateway and one on a Tokyo gateway are both visible
   to the same queue and can be matched, unlike today's single-process
   `Matchmaker._waiting` dict, which only ever sees seekers connected to it.
3. Once matched, the Matchmaker acquires a room-ownership lease (section 3) on an
   available Game-hosting worker and publishes a low-volume `game-created`
   control-plane event carrying `{room_id, worker_address}` back to both players'
   gateways.
4. Each Gateway opens the direct, high-frequency **data-plane** stream (section 2) to
   that specific worker. **Join Room** for an arbitrary `room_id` works identically:
   any Gateway looks up the current owner in the room registry and opens the same
   kind of stream. A spectator does the same, just without ever being granted the
   write lease - a pure subscriber.

### Failure modes (explicitly required by the brief)

| Component fails | Effect | Recovery |
|---|---|---|
| A Game-hosting worker/Docker dies mid-game | Both clients lose their socket at the same instant; in-memory room state (not persisted) is gone | Orchestrator health-check notices the worker is gone; its room lease (section 3) simply expires, so no Gateway can route a new joiner into it. Given a game only lasts 30-90 seconds, the honest answer is to let the game end/fail gracefully (no rating penalty) and let both players re-queue, rather than engineering full mid-game state replication for such a short match - real-time chess also has pieces mid-flight/mid-interception, so an exact snapshot-resume risks a visibly wrong replay for a marginal benefit |
| A Matchmaker instance dies | No data is lost - the seeker queue and room registry live in Redis, not in that instance's own memory (unlike today's single-process dict) | Orchestrator restarts it; the replacement resumes serving the same shared queue immediately |
| Redis dies | The most serious failure, since everything above depends on it | Redis Cluster/Sentinel with replication; already-*running* games are unaffected (they only need their own two sockets) - only *new* matchmaking/room-joins pause fleet-wide until it recovers |
| The Accounts DB dies | New logins/registrations fail | Already-running games are unaffected until their game-over rating write, which should be buffered/retried (a small outbox via the control-plane broker) rather than silently lost; mitigate with a replicated, multi-availability-zone DB with automatic failover |

## 8. Question 3 - network traffic for one active player (~1 move every 2 seconds)

Client -> server per move is tiny: a click message is about 40-60 bytes of JSON
(`{"type": "select_or_move", "row": r, "col": c}`) - negligible even at one every
couple of seconds.

The real cost is the **server -> client state broadcast** - and reading the actual
running code changes the answer here. Today's implementation resends the *entire*
board as JSON at a fixed 15 times/second, regardless of whether anything changed.
Measured directly against the real code (a full starting-position board, serialized
exactly the way `game_room.py` sends it): **~5.6KB per `StateMessage` snapshot.**

| Scenario | Basis | Downstream per player | Fleet-wide at 10M concurrent |
|---|---|---|---|
| Literal premise (each player's own move only, ~150B message, naive) | 1 move/2s × ~150B | ~75 B/s | ~6 Gbps |
| **Current code, unmodified, measured** | 5.6KB × 15/sec | ~84 KB/s | ~6.7 Tbps |
| Target design: sparse move-start event + client-side interpolation | both seats move -> ~1 event/sec visible per player × ~150-250B | ~150-250 B/s | ~12-20 Gbps |

The current design is **not viable at all** at this scale - no realistic
infrastructure absorbs several terabits of egress from one logical service, for a
game whose actual information content is one integer move roughly every two seconds.
More Dockers alone would not fix this - it would just spread 6.7 Tbps across more
machines, not shrink it. The fix has to be a protocol change: send a sparse event only
when a piece starts moving (piece id, `from`, `to`, start time, duration - matching
the `progress`/`target_position`/`remaining_fraction` fields `PieceView` already
carries) and let the client animate between events itself. This isn't a new
technique for this codebase - `renderer.py`'s `BoardView.lerp_pixel` already
interpolates a piece's on-screen position between `position` and `target_position`
using `progress` on the *client* side; the only change is *how often the server needs
to resend the inputs to that interpolation* - once per move instead of once per tick.

## 9. Question 4 - games last 30-90 seconds; what does that mean for Docker roles?

By Little's Law: 5,000,000 concurrent games ÷ ~60s average lifetime implies:

```
5,000,000 games / 60s ≈ 83,000 games starting - and ending - every second, globally
```

That's continuous churn, not a one-time cost, with concrete consequences:

- **Matchmaking tier** must sustain ~83,000 match-and-create decisions per second,
  continuously, forever - favoring many small, horizontally-sharded matchmaker
  instances (partitioned by rating band and/or region) over one central matchmaker
  like today's single `Matchmaker` class.
- **Game-hosting tier** reinforces section 4's warm-pool conclusion: at this churn
  rate, cold-starting a container per match is untenable; rooms need to be cheap to
  spin up and tear down, whether that's "assign from a warm pool" or "start one more
  asyncio task inside an already-running worker."
- **Accounts service** sees a matching ~83,000 rating-update writes/sec sustained,
  globally - reinforcing section 6's answer that this write path needs a dedicated,
  horizontally-scalable service, not a single SQLite file.
- **Rolling deploys/scale-down become cheap**: a Game-hosting worker being retired
  just stops accepting new rooms and drains its existing ones (bounded, ≤90s wait)
  before exiting - no live-migration machinery needed, unlike a service with
  hours-long sessions.

One upside worth naming explicitly: because games are so short-lived, the system
**rebalances fast** - an overloaded Game-hosting worker fully drains within about a
minute as its current games finish, so autoscaling can be far more responsive here
than for a genre with hour-long matches.

## 10. Does the capacity actually add up?

Treating the numbers above as planning assumptions to validate, not measurements yet:

- Assume a conservative ~500 concurrent rooms per Game-hosting worker (well inside
  section 5's low-hundreds-to-low-thousands range).
- **Bandwidth per worker** (target design, section 8): 500 rooms x ~1 event/2s x
  ~200B x 2 seats ≈ trivial - well under 1 Mbps, negligible against any node's
  network allocation.
- **Workers needed at peak**: 5,000,000 games / 500 = **~10,000 Game-hosting worker
  processes**.
- **New-room rate per worker**: 83,000 / 10,000 ≈ ~8.3 rooms/sec/worker - cheap, since
  starting a room is just an in-memory allocation (`GameRoom.__init__` today has no
  I/O in its hot path).
- **Gateway tier, independently**: 10,000,000 connections / ~20,000/pod ≈ **~500
  Gateway pods**.

Ten thousand worker processes sounds large in isolation, but it is the expected,
direct consequence of the scale being asked for - the point of this design is that no
single component needs to be huge; it needs to be replicated a lot.

## 11. Why this meets the requirements

1. **100M registered users** - a replicated Postgres/MySQL cluster behind a single
   Accounts service (section 6) comfortably handles the data volume; SQLite is ruled
   out for architectural reasons (single writer, no network protocol), not size.
2. **10M concurrent players, routing, shared rooms, role division** - a Gateway tier,
   a Redis-backed Matchmaker tier with leased room ownership, and a ~10,000-worker
   Game-hosting fleet (sections 1-3, 7, 10), with explicit failure handling for every
   tier.
3. **Network traffic at ~1 move/2s** - measured directly from the real code (~84
   KB/s/player, ~6.7 Tbps fleet-wide unmodified) and identified as the top
   optimization target, with a concrete fix that reuses the client's existing
   interpolation logic (section 8).
4. **30-90 second games** - ~83,000 games/sec of churn (Little's Law) drives the
   warm-pool design, sharded matchmaking, and a dedicated write-scalable ratings path
   (section 9).

## 12. Open questions

- **Cross-region latency**: when two players from distant regions are matched, which
  region's Game-hosting pool hosts the room, and what does that cost the losing
  side's latency? Matchmaking could bias toward same-region pairing, falling back to
  cross-region only when the local ELO pool is too thin.
- **Reconnect routing across regions**: a disconnected client must be able to find its
  room again through *any* Gateway, not just the one that held the original socket -
  works by construction here (the room registry is globally reachable), but needs
  verification under real failover timing.
- **Control-plane broker capacity**: needs explicit sizing for ~83,000
  game-created/game-finished events/sec plus presence churn - low volume relative to
  gameplay traffic, but not zero, and worth a real load test rather than an assumption.
- **Games-per-worker (~500-1,000) and connections-per-Gateway (~20,000)** are planning
  numbers, not measurements - the next real step is benchmarking actual tick cost and
  socket overhead on real hardware to replace them with data.
