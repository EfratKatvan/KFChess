# Kubernetes / K3s manifests

Translates `docker-compose.yml` into the target Server_Design.md section 18
recommends starting on: K3s, with an identical API/manifest surface to full
Kubernetes (so these same files also apply unchanged to a managed EKS/GKE/AKS
cluster, or to Docker Desktop's own Kubernetes, if that's what's available).

## Building the image

These manifests reference `kfchess:latest`, built from the repo's own
`Dockerfile` (Server_Design.md section 17, strategy B - one image, every
role, `SERVICE_ROLE` picks which at container-start). Build it once:

```
docker build -t kfchess:latest .
```

Then get that image onto the cluster's own nodes - the exact step depends on
which cluster this is applied to:

- **K3s** (its own embedded containerd, not the host's Docker):
  ```
  docker save kfchess:latest | k3s ctr images import -
  ```
- **Docker Desktop's Kubernetes**: no import needed - it shares Docker
  Desktop's own image store directly.
- **A real managed cluster** (EKS/GKE/AKS): push to a registry the cluster
  can actually pull from instead, and change every manifest's `image:` field
  accordingly - `imagePullPolicy: IfNotPresent` here assumes a local image is
  already present, which only holds for the two cases above.

## Applying

```
kubectl apply -f k8s/namespace.yaml
kubectl apply -f k8s/secrets.yaml
kubectl apply -f k8s/redis.yaml -f k8s/postgres.yaml -f k8s/nats.yaml
kubectl apply -f k8s/api.yaml -f k8s/matchmaking.yaml -f k8s/game-shard.yaml -f k8s/ws-gateway.yaml
kubectl apply -f k8s/observability.yaml
```

(Applying `namespace.yaml`/`secrets.yaml` first isn't strictly required -
`kubectl apply -f k8s/` applies everything in one pass and Kubernetes
resolves the ordering - but doing it in dependency order the first time
makes any early failure easier to diagnose.)

Check everything actually came up:

```
kubectl get pods -n kfchess
kubectl get svc -n kfchess
```

`ws-gateway` and `grafana` are the only two `LoadBalancer` services (the only
two roles anything outside the cluster ever needs to reach - Server_Design.md
section 2's own "a client never has a socket to a Shard, only ever to a
Gateway" rule, plus an operator's Grafana dashboard). K3s's built-in ServiceLB
(Klipper) satisfies `LoadBalancer` out of the box, even on a single node - no
cloud load-balancer integration required.

## What's deliberately not here yet

- **Agones** for the Game Shard fleet (section 18's own recommendation, once
  shard lifecycle management - ready/allocated/draining - outgrows plain
  Deployment/ReplicaSet semantics). `game-shard.yaml` stays at `replicas: 1`
  specifically because scaling it today, with plain Deployment/Service
  load-balancing, would be a correctness bug, not just a missed optimization -
  see that file's own comment for why (no room-to-worker discovery/routing
  layer exists yet for `ws_gateway.py` to route a reconnect to the *right*
  replica).
- **Multi-region** anything (section 7's own open question) - one namespace,
  one cluster.
- **HorizontalPodAutoscaler** manifests for the roles that genuinely could
  use one (`api`, `ws-gateway`, `matchmaking`) - the replica counts here are
  static, picked to demonstrate multi-replica statelessness, not a real
  capacity plan.
- **NetworkPolicy** resources enforcing the isolation these manifests already
  achieve *by omission* (no `ports:`/ClusterIP-only for `game-shard` and
  `matchmaking`) - a real deployment would make that isolation explicit and
  enforced, not just a consequence of what's left unpublished.
