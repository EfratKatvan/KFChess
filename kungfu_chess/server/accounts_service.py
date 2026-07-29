from __future__ import annotations

from aiohttp import web

from kungfu_chess.logging_config import configure_logging
from kungfu_chess.server import accounts

HOST = "localhost"
PORT = 8766
LOG_FILE = "accounts_service.log"

"""The Accounts/Ratings API Service (Server_Design.md section 1's "API
Gateway" row, section 14 row 1): a thin REST adapter around accounts.py's
existing pure logic - no password hashing, ELO math, or sqlite3 access
happens here, only request/response translation (section 13.2's
ports-and-adapters split). After Stage 1 (section 19), this is the only
process that ever calls accounts.py/accounts_db.py directly; everyone
else (matchmaker.py, game_room.py, server.py) goes through
accounts_client.AccountsClient instead, bounding the number of things
that ever touch the DB regardless of how large the rest of the fleet
grows (section 6)."""


def _auth_json(result: accounts.AuthResult) -> dict:
    if not result.success:
        return {"success": False, "reason": result.reason}
    return {"success": True, "rating": result.rating}


def create_app(db_path: str = accounts.DEFAULT_DB_PATH) -> web.Application:
    async def login(request: web.Request) -> web.Response:
        body = await request.json()
        result = accounts.login(db_path, body["username"], body["password"])
        return web.json_response(_auth_json(result))

    async def register(request: web.Request) -> web.Response:
        body = await request.json()
        result = accounts.register(db_path, body["username"], body["password"])
        return web.json_response(_auth_json(result))

    async def get_rating(request: web.Request) -> web.Response:
        rating = accounts.get_rating(db_path, request.match_info["username"])
        if rating is None:
            return web.json_response({"reason": "no such account"}, status=404)
        return web.json_response({"rating": rating})

    async def update_ratings(request: web.Request) -> web.Response:
        body = await request.json()
        new_winner, new_loser = accounts.update_ratings_after_game(
            db_path, body["winner_username"], body["loser_username"]
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
