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
| **API Gateway** (stateless, many, geo-distributed) | Non-realtime entry point: login/register, room history, account-facing REST calls - no game logic | Client; Accounts service | HTTP/REST | Request rate |
| **WS Gateway** (stateless, many, geo-distributed) | Live-connection entry point: holds the player's WebSocket, forwards gameplay traffic to whichever worker owns their room - also no game logic | Client (WebSocket); Matchmaker (seek requests); the specific Game-hosting worker once matched (direct data-plane stream) | WebSocket (client-facing and worker-facing) | Open connections |
| **Matchmaker service** (a handful of instances, not one) | The "bridge between opponents" - pairs waiting players by ELO from the shared seeker queue; a pure *fairness* decision | WS Gateway; Game Allocator; Redis | HTTP/REST in from WS Gateway; publishes a low-volume "match-found" event | Queue depth |
| **Game Allocator** (a handful of instances) | A deliberately separate concern from matchmaking: given a freshly-matched pair, decides *which* Game-hosting worker has capacity to host the room, and acquires that worker's room-ownership lease (section 3) - a *placement* decision | Matchmaker; Game-hosting fleet; Redis | NATS control events | Allocation rate |
| **Game-hosting workers** (by far the most instances) | Run the real-time game loop - today's `GameRoom` logic, unchanged, just made addressable | Clients directly over WebSocket (via WS Gateway); Accounts service (rating write at game-over); NATS JetStream (durable move log - section 3) | WebSocket to clients; HTTP/REST to Accounts service; NATS for the move log | Active-room count / CPU |
| **Accounts/Ratings service** (small, few instances) | The *only* thing that talks to the SQL database directly - login, register, rating reads/writes, the final move-history summary per finished game | Postgres/MySQL cluster; called by API Gateway and by Game-hosting workers | SQL wire protocol to the DB; HTTP/REST to its callers | Request rate |
| **Redis** (shared coordination store) | Seeker queue, room-ownership registry (`room_id` -> hosting worker, leased - see section 3), presence/reconnect routing | Matchmaker, Game Allocator, WS Gateway, Game-hosting workers | Redis protocol (RESP) | Lookup/lease rate |
| **NATS** (control-plane bus, with JetStream for durable move-logging) | Low-volume events (match-found, game-finished, presence) *and*, via JetStream, a short-retention durable log of in-progress moves per room, for crash recovery (section 3) | Matchmaker, Game Allocator, Game-hosting workers | NATS / JetStream protocol | Event rate; JetStream storage (bounded - ~90s retention per room) |
| **Observability** (its own small fleet) | Logs, metrics, alerts, distributed traces, load-test tooling - not on any player's hot path, but essential for operating a fleet this size | Read-only telemetry from every other role | Metrics scrape (e.g. Prometheus) / trace export (e.g. OTLP) | Its own concern, not covered further here |
| **Orchestrator** (Kubernetes / K3s, with Agones managing the Game-hosting fleet specifically) | Starts, stops, restarts, and scales the Docker fleet; health-checks workers | Everything (control plane, not the data path) | - | - |

This directly answers what the brief asks about: the Matchmaker and the Game
Allocator are each their **own** process, deliberately, because "who should play
whom" (fairness) and "which physical worker has room for this game" (placement) are
different concerns; and "does everyone reach the same place" is exactly what the
Gateway tier (API + WS) solves - every client's first hop is one of *many*
interchangeable gateway instances, not one fixed address.

## 2. Two kinds of traffic need two kinds of transport

Not everything above should share one pipe. Two very different traffic shapes exist:

- **Control plane** - low volume, latency-tolerant: matchmaking decisions, room
  creation, game-finished notifications, presence changes. **NATS** suits this well -
  the decoupling is valuable (a WS Gateway publishing "player wants a match" doesn't
  need to know in advance which worker will end up hosting it), and the volume is low
  enough that broker overhead is a non-issue.
- **Data plane** - high volume, latency-sensitive: the live gameplay stream itself,
  up to 15 broadcasts/sec *per active room* (today's `BROADCAST_INTERVAL_SECONDS`).
  This must be a **direct stream** from the WS Gateway to the *specific* Game-hosting
  worker that owns the room (resolved once via the room registry), not routed through
  NATS on every tick. Pushing the full gameplay volume (section 8: multiple Tbps at
  this scale, before optimization) through a general-purpose broker would make the
  broker itself the bottleneck - NATS carries the low-volume control events and the
  JetStream move log (section 3), never the raw gameplay stream itself.

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

### Recovering a crashed room without losing the game

A registry and a lease answer "who owns this room" - they don't answer what happens
to the *game itself* once that owner disappears. Simply voiding a crashed room and
sending both players back to matchmaking is the cheaper, more common choice in the
industry, and it's defensible - but it's a poor experience for the two players who
were mid-game, the same way losing an unsaved document is, regardless of how the
crash happened. Since `GameEngine`'s `RealTimeArbiter` already computes every piece's
position and cooldown as a deterministic function of *elapsed time since each move
started* - not some hidden mutable state - a crashed room's state is cheap to
reconstruct from its move history, rather than lost outright or fully replicated:

- Every accepted move (`MoveLoggedEvent` - already carries `elapsed_ms`) is published
  to a **NATS JetStream** stream scoped to that `room_id`, alongside the low-volume
  control events elsewhere on NATS. Unlike that control traffic, this needs a
  durable, ordered, replayable log - JetStream (not plain pub/sub) is built for
  exactly that.
- Retention is short and bounded on purpose: a room's stream only needs to live for
  the room's lifetime (at most 90 seconds) plus a small grace window - never an
  ever-growing dataset.
- On a worker crash, the **Game Allocator** notices (the orchestrator's health-check,
  plus the room lease expiring), assigns a *replacement* worker for each room that
  worker held, and that new worker replays the room's JetStream stream: rebuild the
  board from `STARTING_POSITION`, apply each `MoveLoggedEvent` in order, and use the
  recorded timestamps to work out which pieces are still mid-flight or cooling down
  *right now* - the same math `RealTimeArbiter` already does, just run forward from
  history instead of from live ticks.
- The new worker then acquires the room's lease (with priority, since the Game
  Allocator specifically routed it there) and starts ticking normally; both players'
  WS Gateways are redirected to the new worker address via the room registry.
- This was weighed against a **paired hot-standby worker** (mirroring every room live
  onto a second process, so failover is instant with no replay at all) and rejected
  for cost: that would roughly double the entire Game-hosting fleet's footprint,
  forever, to shave a brief, bounded replay gap down to near-zero - a poor trade for
  a 30-90 second casual match. JetStream replay costs almost nothing extra per
  worker (the durable copy lives in the JetStream cluster, not duplicated on every
  worker) at the price of a short, bounded reconnect gap instead of a seamless one.
- Postgres still only ever receives the **final** move-history summary once a game
  actually ends (matching section 9's ~83,000 writes/sec) - it was never a candidate
  for the *live* log itself: at 10M concurrent players moving roughly every 2
  seconds, that's on the order of 5,000,000 move-events/sec system-wide, far beyond
  what a relational database is built to sustain as a continuous write stream.
  JetStream, an append-only log by design, is the right tool for that volume;
  Postgres is the right tool for the durable, low-frequency summary.

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

1. A player logs in via the nearest **API Gateway** (login/register, no game logic),
   then opens a live connection through the nearest **WS Gateway** (also no game
   logic - it only holds the socket and forwards traffic).
2. **Play** -> WS Gateway forwards to the Matchmaker, which sees every waiting player
   *globally* (the shared Redis-backed queue - section 1), not just players on this
   one Gateway. A player on a US gateway and one on a Tokyo gateway are both visible
   to the same queue and can be matched, unlike today's single-process
   `Matchmaker._waiting` dict, which only ever sees seekers connected to it.
3. Once matched, the Matchmaker hands off to the **Game Allocator** - deliberately a
   separate service, since "who should play whom" (fairness) and "which physical
   worker has room for this game" (capacity/placement) are different concerns. The
   Game Allocator picks an available Game-hosting worker, acquires its
   room-ownership lease (section 3), and publishes a low-volume `match-found`
   control-plane event carrying `{room_id, worker_address}` back to both players' WS
   Gateways.
4. Each WS Gateway opens the direct, high-frequency **data-plane** stream (section 2)
   to that specific worker. **Join Room** for an arbitrary `room_id` works
   identically: any WS Gateway looks up the current owner in the room registry and
   opens the same kind of stream. A spectator does the same, just without ever being
   granted the write lease - a pure subscriber.

To be precise about what "who's on which server" actually means, since it's easy to
conflate three different things: a player's **Gateway connection** is incidental and
stateless (any Gateway works, nothing about it needs to be recorded per-player); the
**shared seeker queue** (Redis) only holds a player while they're waiting to be
matched; **room ownership** (the lease from section 3) is the one mapping that
actually matters for "who's on which server," and it only comes into existence the
instant a match happens - not at login.

### Failure modes (explicitly required by the brief)

| Component fails | Effect | Recovery |
|---|---|---|
| A Game-hosting worker/Docker dies mid-game | Both clients lose their socket at the same instant; the crashing worker's own in-memory state is gone | Orchestrator health-check plus the expiring room lease (section 3) tell the Game Allocator the worker is gone; it assigns a replacement worker per affected room, which **replays that room's NATS JetStream move log** (section 3) to reconstruct the board and re-acquires the lease - both WS Gateways redirect to the new worker. A short, bounded reconnect gap (at most ~90 seconds' worth of moves to replay, typically far less) - the game continues instead of being voided |
| A Matchmaker instance dies | No data is lost - the seeker queue and room registry live in Redis, not in that instance's own memory (unlike today's single-process dict) | Orchestrator restarts it; the replacement resumes serving the same shared queue immediately |
| Redis dies | The most serious failure, since everything above depends on it | Redis Cluster/Sentinel with replication; already-*running* games are unaffected (they only need their own two sockets) - only *new* matchmaking/room-joins pause fleet-wide until it recovers |
| The Accounts DB dies | New logins/registrations fail | Already-running games are unaffected until their game-over rating write, which should be buffered/retried (a small outbox via the control-plane broker) rather than silently lost; mitigate with a replicated, multi-availability-zone DB with automatic failover |

**On geography and resilience**: it's tempting to think "host everything in one
especially stable, secure location" - but the real answer is the opposite: no single
location, however stable, should be trusted to never fail (power, fire, a cut fiber
line, or worse). The Redis clustering and multi-availability-zone DB failover above
already assume this - they exist specifically so the system survives losing an
*entire physical location*, not just a single machine. Game-hosting workers
themselves should run across multiple regions for the same reason, with Gateways
routing each player to their nearest healthy region.

**Naming the reference scenario explicitly, per component**: every piece of state in
this design answers the same underlying question - reconstruct after failure, or
accept losing it? - and the answer genuinely differs by component, worth stating
plainly rather than leaving implicit. For live game/board state, the reference
scenario is *"a crashed room should recover, not vanish"* (section 3's JetStream
replay) - affordable to build because the physics is a deterministic function of
time and move history, and because retention only ever needs to cover a single
~90-second game, not a growing dataset. For ratings/account data, the reference
scenario is stricter still - *"an update must never be silently lost"* - hence the
buffered/retried write and the replicated DB; a wrong or missing rating update has
no cheap recovery path the way a board position does. A **paired hot-standby
worker** (mirroring every room live onto a second process, so failover is instant
with no replay at all) was also considered and rejected here specifically for cost:
it would roughly double the Game-hosting fleet's footprint, forever, to shave a
brief, bounded replay gap down to near-zero - a poor trade for a 30-90 second casual
match.

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

**A second, smaller stream**: section 3's JetStream move log adds its own write
volume, separate from all of the player-facing traffic above - since it's written
once per move rather than multiplied by however many recipients see it, it's roughly
5,000,000 moves/sec system-wide x ~150-250B ≈ **~6-10 Gbps** into the JetStream
cluster - the same order of magnitude as the fixed target-design row above, and
comfortably within what a purpose-built append-only log is designed to sustain
(unlike writing that same volume directly into Postgres).

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
  horizontally-scalable service, not a single SQLite file. Note this scales
  differently from every stateless tier above: the Accounts *service* itself can run
  as more identical instances, but the *database* behind it scales via
  **replication** (a primary plus synced replicas) - not by running more unrelated
  copies of it the way a stateless worker scales.
- **Rolling deploys/scale-down become cheap**: a Game-hosting worker being retired
  just stops accepting new rooms and drains its existing ones (bounded, ≤90s wait)
  before exiting - no live-migration machinery needed, unlike a service with
  hours-long sessions.
- **Bounded replay cost**: the same short game length driving the conclusions above
  also caps how much a crashed room's replacement worker ever needs to replay
  (section 3) - at most ~90 seconds' worth of moves, typically far less.

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
2. **10M concurrent players, routing, shared rooms, role division** - a split
   API/WS Gateway tier, a Redis-backed Matchmaker paired with a separate Game
   Allocator (fairness and placement kept as distinct concerns), leased room
   ownership with JetStream-based crash recovery, and a ~10,000-worker Game-hosting
   fleet (sections 1-3, 7, 10) - with explicit failure handling for every tier,
   including a crashed room recovering rather than vanishing.
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
- **NATS capacity, two different shapes**: the low-volume control events (~83,000
  match-found/game-finished/sec plus presence churn) need sizing, and separately -
  at a very different scale - so does the JetStream move-log stream (~6-10 Gbps,
  section 8). Both are estimates, not measurements; worth a real load test on each.
- **JetStream replay correctness under real load**: the replay math (section 3)
  assumes `RealTimeArbiter`'s position/cooldown logic can be run forward from
  recorded timestamps with no drift - reasonable given how it's built today, but not
  yet verified against a real crash-and-replay test.
- **Games-per-worker (~500-1,000) and connections-per-Gateway (~20,000)** are planning
  numbers, not measurements - the next real step is benchmarking actual tick cost and
  socket overhead on real hardware to replace them with data.

## 13. From six logical components to four deployable units

Everything above answers *why* to distribute; this section and the ones that follow
answer *how to actually package it* - concretely, as Docker images this codebase can
be built into. The project brief lists six logical components (API Gateway, WebSocket
Gateway, Matchmaker, Game Allocator, Game Server Shards, Observability) plus a
recommended stack (NATS/Redis PubSub, Redis, PostgreSQL, Docker Compose, K8s/K3s). A
logical component is not automatically its own container - the right grouping
question is: **do these components share the same exposure surface and the same
scaling profile?** Combine when yes; keep separate when they differ in protocol,
statefulness, or blast radius:

| Rule | Applied here |
|---|---|
| Bundle services with the same exposure (protocol) and the same scaling profile | Login/Rooms(REST)/Rating are all plain REST, stateless, backed by Postgres - they'd scale identically (more replicas behind a load balancer) |
| Keep separate anything that differs in protocol / statefulness / blast radius | WebSocket is a stateful, long-lived connection (scales on connection count, not QPS); a Game Server Shard holds live state in memory and its crash only affects the rooms it hosts |
| Cross-cutting infrastructure is not a "service" at all | Observability is never its own application container - it's Prometheus/Grafana/logs reading telemetry from everything else |

**Result: 6 logical components -> 4 deployable units + Observability as infra:**

1. **API Service** = Auth + Rooms(REST) + Rating/History -> one Docker image
2. **Matchmaking Service** = Matchmaker + Game Allocator -> one Docker image
3. **WS Gateway** -> stays separate (different protocol/statefulness)
4. **Game Server Shards** -> stays separate (blast radius, holds live state)
5. **Observability** -> infra, not an application container

### 13.1 The real grouping criterion is "same required infrastructure," not just "same layer"

A sharper version of the rule above: two components are worth bundling not just
because they're logically similar, but because they need the **same
infrastructure/dependencies (the same `pip install`) and the same "level" of protocol
exposure**. If two components both need Redis and NATS at the same level, and their
dependency sets are identical, the only real difference between them is *which
endpoint gets called* (e.g. `/room` vs. `/calculation`) - and at that point bundling
them is an economic decision, not just a logical one. This is exactly the case for
Matchmaker + Game Allocator: both need Redis and NATS, both are lightweight and
non-realtime from the client's point of view - they belong in the same deployable
unit not merely because they're sequential steps in one pipeline, but because they'd
need identical infrastructure regardless.

### 13.2 Separate pure logic from its transport adapter (ports & adapters)

The existing code already demonstrates the right shape for this: `accounts.py` is
pure logic (password hashing, ELO math, `AuthResult`) with zero knowledge of how it's
reached - `server.py` happens to wrap it in a WebSocket call today, but it could just
as easily be wrapped in an HTTP handler without changing a single line of the logic
itself. **This is the principle to apply to all four deployable units**: internal
decisions (`"are these two players an ELO match?"`, `"which worker has room?"`)
should always be plain functions with no idea whether they were invoked from an HTTP
handler, a NATS subscriber, or a unit test. Each deployable unit is *pure logic* +
one or more thin *adapters* (a REST adapter, a NATS adapter) wrapping it - which also
keeps the door open to wrapping the same logic in a different protocol later without
touching it.

## 14. Mapping current code to deployable units

| # | Logical component (brief) | Deployable unit | Protocol | Scales on | Current code that moves there |
|---|---|---|---|---|---|
| 1 | API Gateway (login/rooms/history) | **API Service** | HTTP/REST | request rate | `accounts.py` + `accounts_db.py` - almost 1:1, already networking-free and takes `db_path` as a parameter |
| 5 (part) | Rating/History | **API Service** (same unit) | HTTP/REST | request rate | part of `accounts.py` (`update_ratings_after_game`) - the call moves from `game_room.py` writing the DB directly to an internal HTTP call to the API Service |
| 2 | WebSocket Gateway | **WS Gateway** | WebSocket | open-connection count | `server.py` (`_handle_connection`, `serve(...)`) - just the socket acceptance; auth logic moves to the API Service, the gateway only routes |
| 3 | Matchmaker | **Matchmaking Service** | internal (NATS/HTTP) | queue depth | `matchmaker.py` - the `_waiting`/`_find_opponent_within_elo_range` part (fairness/ELO only) |
| 4 | Game Allocator | **Matchmaking Service** (same unit) | internal (NATS) | allocation rate | `matchmaker.py` - the part that today **instantiates `GameRoom` directly** (`_start_seeking`, `_join_room`) - exactly the placement decision that needs to become its own responsibility inside the same unit |
| - | Room Registry (Create/Join) | Redis, owned by the Matchmaking Service | Redis protocol | - | `rooms.py` (`RoomRegistry`, `Room`) - already pure, I/O-free logic; moves almost as-is into a Redis schema |
| 5 | Game Server Shards | **Game Server Shards** | WebSocket (data-plane from the Gateway) | active-room count / CPU | `game_room.py` (`GameRoom`) + `kungfu_chess/engine/*` - the game logic itself barely changes; only *who* it sends to/receives from changes (never the client directly, always a stream the WS Gateway routes) |
| 6 | Observability | separate infra, not an application container | Prometheus scrape / OTLP | - | doesn't exist yet - added as logging/metrics in every unit |
| - | Wire protocol | shared library imported by all four units | - | - | `protocol.py`, `messages.py`, `serialization.py` - unchanged in shape, just becomes a package shared across units |

### 14.1 Scope of a Game Server Shard: only the "live game" window

Worth stating explicitly: a Shard is responsible for neither the administrative start
nor the administrative end of a game - only the window during which it's *live*:

- **Game start** (deciding which worker hosts it, acquiring the lease) -> the **Game
  Allocator**'s job (inside the Matchmaking Service), *before* the Shard has even
  heard of the room.
- **The live game itself** (tick loop, accepting moves, broadcasting) -> the **Game
  Server Shard**'s job alone - exactly what `GameRoom._run` already does today.
- **Game end** (rating update, DB write, releasing the lease, clearing the room
  registry entry) -> split between the Shard (releases its lease, requests the rating
  update) and the **API Service** (which actually performs the Postgres write - the
  one DB choke point from section 6).

The Shard is deliberately a "thin in time" layer - it enters the picture only after
allocation and exits it the instant the game ends, with no knowledge of what happens
before or after.

### 14.2 WS Gateway: stateful per connection, stateless as a fleet

A question worth answering explicitly: should the Gateway be stateless? It depends on
which level you're looking at. A **single connection** is inherently stateful - a
live TCP/WebSocket socket exists for as long as the player is connected. But **the
fleet as a whole** can and should be stateless: no specific Gateway instance "owns" a
given player - if a connection drops, the player can reconnect through *any* other
Gateway instance, because reconnect/presence mapping lives in Redis, not in that
Gateway process's own memory. This is the same point made in section 7 ("a player's
Gateway connection is incidental and stateless") - the thing to verify at
implementation time is that no data structure inside the Gateway's own code holds
anything that needs to survive that specific instance crashing.

## 15. End-to-end flow of the target architecture

```
Client
  --(HTTP: login/register/rooms/history)--> API Service --> PostgreSQL
  --(WebSocket, live)--> WS Gateway
      WS Gateway --(seek/create/join room)--> Matchmaking Service
          Matchmaker  <--> Redis (shared seeker ZSET, room registry+lease)
          Game Allocator <--> Redis
          Game Allocator --(NATS: match-found, allocate)--> NATS
      NATS --(notifies)--> WS Gateway
      WS Gateway ==(data-plane: moves/state, 10-15Hz, direct)==> Game Server Shard
          Game Server Shard --(move log)--> NATS JetStream
          Game Server Shard --(rating update at game-over)--> API Service
          Game Server Shard --(heartbeat/lease renew)--> Redis
  Observability reads metrics/logs from API Service, WS Gateway,
  Matchmaking Service and every Game Server Shard - never on any player's
  request path.
```

Step by step:

1. **Login**: the client calls the **API Service** (REST) for login/register ->
   reads/writes PostgreSQL, gets back a session/token.
2. **Live connection**: the client opens a WebSocket against the **WS Gateway** (not
   the API Service - different protocol, different scaling axis).
3. **Seeking a match**: clicking "Play" -> the WS Gateway forwards a seek request to
   the **Matchmaking Service**. Its internal `Matchmaker` looks at the shared queue in
   Redis (not a local dict, as today) and finds an ELO-appropriate opponent.
4. **Allocation**: once paired, the `Matchmaker` hands the decision to the `Game
   Allocator` (**same deployable unit**, separate responsibility in code) - it picks
   an available Game Server Shard, acquires its lease in Redis
   (`SET room:<id>:owner <worker> NX PX 5000`), and publishes a `match-found` event on
   NATS.
5. **The game itself**: the WS Gateway, having heard the event, opens a direct
   data-plane stream between the client and the specific assigned Shard - **not
   through NATS**, since the volume is too high (sections 2 and 8). The Shard runs
   `GameEngine`/`RealTimeArbiter` exactly as it does today.
6. **Game end**: the Shard sends a rating-update request to the API Service (an
   internal HTTP call, not a direct DB write as today) and releases its Redis lease.
7. **Observability** reads metrics/logs from all four units throughout - never part of
   any player's request path.

## 16. Two concrete infrastructure decisions

### 16.1 The matchmaking queue must be a Redis ZSET, not a linear scan

Today, `matchmaker.py`'s `_find_opponent_within_elo_range` (line 216) loops over
**every** waiting player (`self._waiting.values()`) until it finds one inside the ELO
range - O(n) per match attempt. The right Redis structure is a **ZSET** (sorted set):
`ZADD seekers:queue <rating> <user_id>` on entering the queue, then finding candidates
in-range via `ZRANGEBYSCORE seekers:queue <rating-100> <rating+100>` - a logarithmic
range query (`O(log n + m)`, where `m` is the number of results in range) instead of a
scan over the whole queue. Worth locking in now, as part of moving the seeker queue
from an in-memory dict to Redis (roadmap stage 0, section 17).

### 16.2 NATS vs. Redis Pub/Sub for the control plane

The brief lists "NATS / Redis PubSub" as two options for the control plane - a real
decision worth making explicit rather than leaving implicit:

| | Redis Pub/Sub | NATS (+ JetStream) |
|---|---|---|
| Extra infra to run | none - Redis is already required anyway | a separate system (extra Docker/ops cost) |
| Durability | **none** - a message to a subscriber that isn't currently connected is simply lost | JetStream retains a durable log for a bounded time, replayable |
| Where we actually need durability | - | the move log for crashed-room recovery (section 3) - **required**, not a nice-to-have |
| Complexity | very simple, no extra API to learn | a dedicated API, but richer capacity/routing too |

**Recommendation**: use NATS+JetStream as the brief suggests, specifically because
crashed-room recovery genuinely needs durability that Redis Pub/Sub cannot provide.
That said, if the immediate goal is only a **local Docker Compose** for development,
without crash recovery yet, it's reasonable to start with Redis Pub/Sub for the
lightweight control events (match-found, game-ended) to save one infra piece in the
early roadmap stages, and add NATS+JetStream only once crashed-room recovery is
actually implemented. This is an intentionally open decision, not a settled one.

## 17. Docker packaging: one image with roles, vs. one Dockerfile per unit

Section 13's four deployable units don't necessarily mean four separate `Dockerfile`s.
Since all four units share the same codebase (Python, the same
`protocol.py`/`messages.py`, largely overlapping pip dependencies), two packaging
strategies are both legitimate:

| Strategy | How it works | Pro | Con |
|---|---|---|---|
| **A. A separate Dockerfile per unit** (4 images) | each unit is its own container, with only the dependencies it actually needs | small, precise image per role, full build isolation | 4 files to maintain, 4 build pipelines |
| **B. One Docker image, "role" chosen at run time** | a single `Dockerfile` installs every dependency; the role (`api` / `ws-gateway` / `matchmaking` / `game-shard`) is chosen by an entrypoint argument or `SERVICE_ROLE` env var - all four entries in `docker-compose.yml` share the same `image:`/`build:`, differing only in `command:`/`environment:` | one Dockerfile to maintain, guaranteed dependency-version consistency across units (no drift between images), fewer CI pipelines | a somewhat larger image (bundles dependencies only some roles use) |

**Recommendation**: start with **strategy B** (one image, roles chosen at run time) -
this both matches the observation that the `pip install` set is nearly identical
across units and that the real difference between them is just *which endpoint gets
hit*, and it doesn't compromise anything about scaling: `docker-compose.yml` (and
later Kubernetes) still runs four separate `services:`/`Deployments` from that one
image, each with its own replica count and autoscaling metric - exactly as it would
with four separate images, just built from one `Dockerfile`. If a specific role (e.g.
Game Server Shard) later needs a heavy, unique dependency the other roles don't - that
is the natural point to split *that one role* into its own Dockerfile, without
touching the rest.

## 18. Staged implementation roadmap

Suggested stages for actually building this (each stage leaves the system working):

1. **Stage 0**: add Redis as a dependency; move `Matchmaker._waiting`/`_rooms`/
   `RoomRegistry` from in-memory dicts to Redis (as a ZSET-backed queue, section 16.1)
   - still one process.
2. **Stage 1**: split `accounts.py`/`accounts_db.py` into a standalone API Service
   (HTTP); `server.py` calls it over HTTP instead of importing it directly.
3. **Stage 2**: split socket acceptance itself (`server.py`) into a separate WS
   Gateway that talks to the rest of the system (still one process at this stage)
   over Redis/HTTP.
4. **Stage 3**: actually split `matchmaker.py` into its two responsibilities
   (Matchmaker fairness + Game Allocator placement) inside one Matchmaking Service
   process, with lease-based room ownership in Redis.
5. **Stage 4**: `game_room.py` becomes a standalone Game Server Shard, receiving
   commands from and sending state to the WS Gateway rather than the client directly;
   replace the full-snapshot broadcast (~5.6KB/tick) with the sparse-event protocol
   (section 8).
6. **Stage 5**: package per section 17's decision (recommended: one image, role chosen
   via `SERVICE_ROLE`) + a local `docker-compose.yml` running everything alongside
   Redis/NATS/Postgres.
7. **Stage 6**: add Observability (logs/metrics/health checks/load tests) + K8s/K3s
   manifests.

Verification at each stage: `python -m pytest` should keep passing, and two client
processes (`python app.py` run twice) should still be able to connect, get matched,
and play a game to completion - the same manual check `README.md` already describes.
