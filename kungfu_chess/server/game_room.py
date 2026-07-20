from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, Optional

from websockets.asyncio.server import ServerConnection

from kungfu_chess.engine.board_view_state import BoardViewState
from kungfu_chess.engine.game_engine import GameEngine
from kungfu_chess.input.controller import Controller
from kungfu_chess.io.board_parser import build_board
from kungfu_chess.model.piece import KING, WHITE, BLACK
from kungfu_chess.model.position import Position
from kungfu_chess.realtime.real_time_arbiter import RealTimeArbiter
from kungfu_chess.rules.rule_engine import RuleEngine
from kungfu_chess.server import accounts
from kungfu_chess.server.messages import JumpMessage, MatchFoundMessage, RestartMessage, SelectOrMoveMessage, StateMessage
from kungfu_chess.server.serialization import serialize_message
from kungfu_chess.starting_position import STARTING_POSITION
from kungfu_chess.view.observers import MoveLogObserver, ScoreObserver

TICK_SECONDS = 0.016


class GameRoom:
    """Owns one authoritative game (board/rules/arbiter/engine) shared by
    exactly two connections, one per color - the server-side counterpart
    of what app.py's build_game() + image_view.run()'s loop do locally
    for a single-process game. Runs its own real-time tick loop and
    broadcasts a personalized snapshot to each connection every tick.
    Also applies one ELO rating update (see server/accounts.py) the
    instant a game actually ends."""

    def __init__(
        self,
        white_ws: ServerConnection, white_username: str,
        black_ws: ServerConnection, black_username: str,
        db_path: str = accounts.DEFAULT_DB_PATH,
    ) -> None:
        self._connections: Dict[str, ServerConnection] = {WHITE: white_ws, BLACK: black_ws}
        self._usernames: Dict[str, str] = {WHITE: white_username, BLACK: black_username}
        self._db_path = db_path
        self._tick_task: Optional[asyncio.Task] = None
        self._build_fresh_game()

    def _build_fresh_game(self) -> None:
        board = build_board(STARTING_POSITION)
        rule_engine = RuleEngine(board)
        arbiter = RealTimeArbiter(board)
        self._engine = GameEngine(board, rule_engine, arbiter)
        self._controllers: Dict[str, Controller] = {
            WHITE: Controller(mapper=None, engine=self._engine, owner_color=WHITE),
            BLACK: Controller(mapper=None, engine=self._engine, owner_color=BLACK),
        }
        self._move_log = MoveLogObserver()
        self._engine.add_observer(self._move_log)
        self._score = ScoreObserver()
        self._engine.add_observer(self._score)
        self._last_tick = time.perf_counter()
        self._rating_update_applied = False

    async def start(self) -> None:
        for color, ws in self._connections.items():
            await self._safe_send(ws, MatchFoundMessage(color=color))
        self._tick_task = asyncio.create_task(self._run())

    def stop(self) -> None:
        if self._tick_task is not None:
            self._tick_task.cancel()

    def color_of(self, ws: ServerConnection) -> Optional[str]:
        for color, connection in self._connections.items():
            if connection is ws:
                return color
        return None

    async def handle_message(self, color: str, message: Any) -> None:
        controller = self._controllers[color]
        if isinstance(message, SelectOrMoveMessage):
            controller.handle_cell(Position(message.row, message.col))
        elif isinstance(message, JumpMessage):
            controller.handle_jump_cell(Position(message.row, message.col))
        elif isinstance(message, RestartMessage):
            if self._engine.is_game_over():
                self._build_fresh_game()

    async def _run(self) -> None:
        while True:
            await asyncio.sleep(TICK_SECONDS)
            now = time.perf_counter()
            dt_ms = int((now - self._last_tick) * 1000)
            self._last_tick = now
            self._engine.wait(dt_ms)
            await self._broadcast()

    async def _broadcast(self) -> None:
        view_state = self._engine.snapshot(move_log=self._move_log.as_dict(), scores=self._score.as_dict())
        if view_state.game_over:
            self._apply_rating_update(view_state)
        await asyncio.gather(*(
            self._safe_send(ws, self._personalized_message(color, view_state))
            for color, ws in self._connections.items()
        ))

    def _apply_rating_update(self, view_state: BoardViewState) -> None:
        """Runs exactly once per finished game (self-guarding, not just
        relying on _broadcast to check first) - the color whose king is
        no longer on the board lost; the other color's username gets the
        ELO win, the loser's the matching loss (see server/accounts.py)."""
        if self._rating_update_applied:
            return
        self._rating_update_applied = True
        white_has_king = any(p.kind == KING and p.color == WHITE for p in view_state.pieces)
        winner_color = WHITE if white_has_king else BLACK
        loser_color = BLACK if winner_color == WHITE else WHITE
        accounts.update_ratings_after_game(
            self._db_path, self._usernames[winner_color], self._usernames[loser_color]
        )

    def _personalized_message(self, color: str, view_state: BoardViewState) -> StateMessage:
        controller = self._controllers[color]
        selected = controller.selected_pos
        legal_destinations = self._engine.legal_destinations(selected) if selected is not None else set()
        return StateMessage(
            board=view_state,
            your_selected_pos=selected,
            your_legal_destinations=legal_destinations,
            your_invalid_target=controller.invalid_target,
        )

    async def _safe_send(self, ws: ServerConnection, message: Any) -> None:
        try:
            await ws.send(serialize_message(message))
        except Exception:
            pass  # a closed/broken socket is handled by the server's own connection loop, not here
