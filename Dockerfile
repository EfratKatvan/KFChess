# One image, every role (Stage 5, Server_Design.md section 17, strategy
# B): the actual role - api / ws-gateway / game-shard - is chosen at
# container-start by the SERVICE_ROLE env var (see docker_entrypoint.py
# and docker-compose.yml). A larger image that bundles every role's
# dependencies (including opencv-python, only actually used by the
# desktop client, never by any server role) is the accepted trade-off
# strategy B makes explicitly, in exchange for one Dockerfile and no
# dependency-version drift between roles.
FROM python:3.11-slim

# Unset, stdout is fully block-buffered here (no TTY) - every role's
# own logging_config.py StreamHandler would sit invisible until the
# buffer filled or the process exited, making `kubectl logs`/`docker
# logs` show nothing during normal operation. Found the hard way while
# trying to diagnose a live matchmaking issue in k8s and seeing empty
# logs despite real traffic.
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "docker_entrypoint.py"]
