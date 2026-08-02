# One image, every role (Stage 5, Server_Design.md section 17, strategy
# B): the actual role - api / ws-gateway / game-shard - is chosen at
# container-start by the SERVICE_ROLE env var (see docker_entrypoint.py
# and docker-compose.yml). A larger image that bundles every role's
# dependencies (including opencv-python, only actually used by the
# desktop client, never by any server role) is the accepted trade-off
# strategy B makes explicitly, in exchange for one Dockerfile and no
# dependency-version drift between roles.
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "docker_entrypoint.py"]
