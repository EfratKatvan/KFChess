from __future__ import annotations

import asyncio
import os
from functools import partial

from aiohttp import web

from kungfu_chess.logging_config import configure_logging
from kungfu_chess.server import accounts

# Env-overridable (Stage 5, section 17): docker-compose binds this to
# 0.0.0.0 so the container accepts connections from other containers,
# not just itself - "localhost" remains the default for local runs.
HOST = os.environ.get("HOST", "localhost")
PORT = int(os.environ.get("PORT", "8766"))
LOG_FILE = "accounts_service.log"

"""The Accounts/Ratings API Service (Server_Design.md section 1's "API
Gateway" row, section 14 row 1): a thin REST adapter around accounts.py's
existing pure logic - no password hashing, ELO math, or Postgres access
happens here, only request/response translation (section 13.2's
ports-and-adapters split). After Stage 1 (section 19), this is the only
process that ever calls accounts.py/accounts_db.py directly; everyone
else (matchmaker.py, game_room.py, ws_gateway.py) goes through
accounts_client.AccountsClient instead, bounding the number of things
that ever touch the DB regardless of how large the rest of the fleet
grows (section 6).

accounts.py's DB-backed functions are plain blocking calls (psycopg2,
not asyncpg - section 6's migration only needed a real, network-
reachable, replicated database, not an async driver too) - run via
_run_blocking/run_in_executor so one slow query stalls only the request
awaiting it, never every other concurrent request this same event loop
is serving."""


async def _run_blocking(func, *args):
    return await asyncio.get_running_loop().run_in_executor(None, partial(func, *args))


def _auth_json(result: accounts.AuthResult) -> dict:
    if not result.success:
        return {"success": False, "reason": result.reason}
    return {"success": True, "rating": result.rating, "token": result.token}


def create_app(schema: str = accounts.DEFAULT_SCHEMA) -> web.Application:
    async def login(request: web.Request) -> web.Response:
        body = await request.json()
        result = await _run_blocking(accounts.login, schema, body["username"], body["password"])
        return web.json_response(_auth_json(result))

    async def register(request: web.Request) -> web.Response:
        body = await request.json()
        result = await _run_blocking(accounts.register, schema, body["username"], body["password"])
        return web.json_response(_auth_json(result))

    async def get_rating(request: web.Request) -> web.Response:
        rating = await _run_blocking(accounts.get_rating, schema, request.match_info["username"])
        if rating is None:
            return web.json_response({"reason": "no such account"}, status=404)
        return web.json_response({"rating": rating})

    async def update_ratings(request: web.Request) -> web.Response:
        body = await request.json()
        new_winner, new_loser = await _run_blocking(
            accounts.update_ratings_after_game, schema, body["winner_username"], body["loser_username"]
        )
        return web.json_response({"winner_rating": new_winner, "loser_rating": new_loser})

    app = web.Application()
    app.router.add_post("/login", login)
    app.router.add_post("/register", register)
    app.router.add_get("/ratings/{username}", get_rating)
    app.router.add_post("/ratings/update", update_ratings)
    return app


def main() -> None:
    configure_logging(LOG_FILE)
    accounts.init_db()
    web.run_app(create_app(), host=HOST, port=PORT)


if __name__ == "__main__":
    main()
