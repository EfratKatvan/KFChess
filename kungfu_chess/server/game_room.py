from __future__ import annotations

import asyncio
import json
import time
from typing import Dict, Optional

from websockets.asyncio.server import ServerConnection

from kungfu_chess.engine.game_engine import GameEngine
from kungfu_chess.input.controller import Controller
from kungfu_chess.io.board_parser import build_board
from kungfu_chess.model.piece import WHITE, BLACK
from kungfu_chess.model.position import Position
from kungfu_chess.realtime.real_time_arbiter import RealTimeArbiter
from kungfu_chess.rules.rule_engine import RuleEngine
from kungfu_chess.server import protocol
from kungfu_chess.server.serialization import (
    board_view_state_to_wire,
    legal_destinations_to_wire,
    position_to_wire,
)
from kungfu_chess.starting_position import STARTING_POSITION
from kungfu_chess.view.observers import MoveLogObserver, ScoreObserver

TICK_SECONDS = 0.016


class GameRoom:
    """Owns one authoritative game (board/rules/arbiter/engine) shared by
    exactly two connections, one per color - the server-side counterpart
    of what app.py's build_game() + image_view.run()'s loop do locally
    for a single-process game. Runs its own real-time tick loop and
    broadcasts a personalized snapshot to each connection every tick."""

    def __init__(self, white_ws: ServerConnection, black_ws: ServerConnection) -> None:
        self._connections: Dict[str, ServerConnection] = {WHITE: white_ws, BLACK: black_ws}
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

    async def start(self) -> None:
        for color, ws in self._connections.items():
            await self._safe_send(ws, {"type": protocol.MATCH_FOUND, "color": color})
        self._tick_task = asyncio.create_task(self._run())

    def stop(self) -> None:
        if self._tick_task is not None:
            self._tick_task.cancel()

    def color_of(self, ws: ServerConnection) -> Optional[str]:
        for color, connection in self._connections.items():
            if connection is ws:
                return color
        return None

    async def handle_message(self, color: str, message: dict) -> None:
        controller = self._controllers[color]
        message_type = message.get("type")
        if message_type == protocol.SELECT_OR_MOVE:
            controller.handle_cell(Position(message["row"], message["col"]))
        elif message_type == protocol.JUMP:
            controller.handle_jump_cell(Position(message["row"], message["col"]))
        elif message_type == protocol.RESTART:
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
        board_wire = board_view_state_to_wire(view_state)
        await asyncio.gather(*(
            self._safe_send(ws, self._personalized_message(color, board_wire))
            for color, ws in self._connections.items()
        ))

    def _personalized_message(self, color: str, board_wire: dict) -> dict:
        controller = self._controllers[color]
        selected = controller.selected_pos
        legal_destinations = self._engine.legal_destinations(selected) if selected is not None else set()
        return {
            "type": protocol.STATE,
            "board": board_wire,
            "your_selected_pos": position_to_wire(selected),
            "your_legal_destinations": legal_destinations_to_wire(legal_destinations),
            "your_invalid_target": position_to_wire(controller.invalid_target),
        }

    async def _safe_send(self, ws: ServerConnection, message: dict) -> None:
        try:
            await ws.send(json.dumps(message))
        except Exception:
            pass  # a closed/broken socket is handled by the server's own connection loop, not here
