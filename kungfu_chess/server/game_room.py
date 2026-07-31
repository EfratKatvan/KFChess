from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Awaitable, Callable, Dict, Optional, Set, Type

from websockets.asyncio.server import ServerConnection

from kungfu_chess.engine.board_view_state import BoardViewState
from kungfu_chess.engine.game_engine import GameEngine
from kungfu_chess.input.controller import Controller
from kungfu_chess.io.board_parser import build_board
from kungfu_chess.model.piece import KING, WHITE, BLACK
from kungfu_chess.model.position import Position
from kungfu_chess.realtime.real_time_arbiter import RealTimeArbiter
from kungfu_chess.rules.rule_engine import RuleEngine
from kungfu_chess.server import protocol
from kungfu_chess.server.accounts_client import AccountsClient
from kungfu_chess.server.messages import (
    JumpMessage,
    MatchFoundMessage,
    OpponentDisconnectedMessage,
    OpponentReconnectedMessage,
    PieceMotionStartedMessage,
    ResignMessage,
    RestartMessage,
    SelectOrMoveMessage,
    StateMessage,
)
from kungfu_chess.server.serialization import serialize_message
from kungfu_chess.starting_position import STARTING_POSITION
from kungfu_chess.events.observers import MotionCollector, MoveLogObserver, ScoreObserver

TICK_SECONDS = 0.016  # physics granularity - engine.wait() runs at this rate regardless of broadcast rate
BROADCAST_INTERVAL_SECONDS = 0.2  # periodic full-snapshot resync rate (section 8) - piece motion itself
# is pushed immediately, unthrottled, as a sparse PieceMotionStartedMessage (see _broadcast_pending_motions);
# this interval now only needs to be fast enough to keep cooldown overlays/scores/move-log reasonably fresh

logger = logging.getLogger(__name__)


class GameRoom:
    """Owns one authoritative game (board/rules/arbiter/engine) shared by
    exactly two connections, one per color - the server-side counterpart
    of what app.py's build_game() + image_view.run()'s loop do locally
    for a single-process game. Runs its own real-time tick loop; a
    piece starting to move is pushed immediately as a sparse
    PieceMotionStartedMessage (_broadcast_pending_motions), while a full
    personalized snapshot of everything else still goes out periodically
    (_broadcast, BROADCAST_INTERVAL_SECONDS - section 8).
    Also applies one ELO rating update (see server/accounts.py) the
    instant a game actually ends - including by auto-resign, if a
    disconnected player doesn't return within the grace period."""

    def __init__(
        self,
        white_ws: ServerConnection, white_username: str,
        black_ws: ServerConnection, black_username: str,
        accounts_client: AccountsClient,
        room_id: Optional[str] = None,
        on_game_over: Optional[Callable[[], Awaitable[None]]] = None,
    ) -> None:
        self._connections: Dict[str, ServerConnection] = {WHITE: white_ws, BLACK: black_ws}
        self._usernames: Dict[str, str] = {WHITE: white_username, BLACK: black_username}
        self._accounts_client = accounts_client
        self._room_id = room_id
        self._on_game_over = on_game_over
        # Spectators live outside _connections (they have no color) - a
        # RestartMessage rebuilds the game via _build_fresh_game but must
        # not drop anyone watching it, so this is initialized here, not there.
        self._spectators: Set[ServerConnection] = set()
        self._tick_task: Optional[asyncio.Task] = None
        self._resign_task: Optional[asyncio.Task] = None
        self._left = False  # room-lifetime, not per-game - see leave(); never reset by _build_fresh_game
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
        self._motion_collector = MotionCollector()
        self._engine.add_observer(self._motion_collector)
        self._last_tick = time.perf_counter()
        self._last_broadcast = time.perf_counter()
        self._rating_update_applied = False
        self._disconnected_color: Optional[str] = None
        self._survivor_also_disconnected = False
        self._paused = False
        if self._resign_task is not None:
            self._resign_task.cancel()
            self._resign_task = None

    def username_of(self, color: str) -> str:
        return self._usernames[color]

    def is_game_over(self) -> bool:
        return self._engine.is_game_over()

    async def start(self) -> None:
        for color, ws in self._connections.items():
            await self._safe_send(ws, await self._match_found_message(color))
        self._tick_task = asyncio.create_task(self._run())

    async def _match_found_message(self, color: str) -> MatchFoundMessage:
        white_rating = await self._accounts_client.get_rating(self._usernames[WHITE])
        black_rating = await self._accounts_client.get_rating(self._usernames[BLACK])
        return MatchFoundMessage(
            color=color,
            white_username=self._usernames[WHITE], white_rating=white_rating,
            black_username=self._usernames[BLACK], black_rating=black_rating,
            room_id=self._room_id,
        )

    async def add_spectator(self, ws: ServerConnection) -> None:
        """Sends one immediate snapshot rather than waiting for the next
        broadcast tick, so a spectator joining mid-game doesn't stare
        at a blank screen for up to one broadcast interval."""
        self._spectators.add(ws)
        view_state = self._engine.snapshot(move_log=self._move_log.as_dict(), scores=self._score.as_dict())
        await self._safe_send(ws, self._spectator_state_message(view_state))

    def remove_spectator(self, ws: ServerConnection) -> None:
        self._spectators.discard(ws)

    async def leave(self, ws: ServerConnection) -> Set[ServerConnection]:
        """Called once a connection explicitly leaves this room after
        it's already finished (see Matchmaker._leave_room and
        on_disconnect, both of which only call this once
        is_game_over() is true). A spectator leaving affects no one
        else. A real player leaving takes the whole room down: their
        opponent has no one left to face a rematch with either, so
        this stops the tick loop for good (nothing should ever
        broadcast to either connection again), frees the room's own
        name in the registry (see on_game_over - NOT fired at
        game-over itself, since both players might still want New
        Game in the same room; only once someone actually leaves does
        the room name genuinely become free again), and returns the
        opponent's connection for the caller to also kick back to the
        lobby."""
        color = self.color_of(ws)
        if color is None:
            self._spectators.discard(ws)
            return set()
        if self._left:
            return set()  # already handled - e.g. a disconnect racing the LeaveRoomMessage that already tore this down
        self._left = True
        opponent_ws = self._connections[_other_color(color)]
        self.stop()
        if self._on_game_over is not None:
            await self._on_game_over()
        return {opponent_ws}

    def stop(self) -> None:
        if self._tick_task is not None:
            self._tick_task.cancel()
        if self._resign_task is not None:
            self._resign_task.cancel()

    def color_of(self, ws: ServerConnection) -> Optional[str]:
        for color, connection in self._connections.items():
            if connection is ws:
                return color
        return None

    async def handle_disconnect(self, color: str) -> None:
        """Pauses the game clock (so the disconnected player doesn't lose
        ground to lag) and starts a grace-period countdown - the
        surviving player is notified once; the client counts down
        locally from there (see OpponentDisconnectedMessage).

        If a *second* disconnect arrives for the color that was still
        "surviving" (nobody at all is connected anymore), that alone
        doesn't cancel the first disconnect's own reconnect grace
        window (see try_reconnect) - it's only recorded so
        _auto_resign_after_grace knows, once its timer actually fires,
        that there's no one left who could ever click "New Game" -
        and so should fully release the room instead of leaving it
        paused forever (see _survivor_also_disconnected below)."""
        if self._engine.is_game_over():
            return
        if self._disconnected_color is not None:
            if self._disconnected_color != color:
                self._survivor_also_disconnected = True
            return
        self._disconnected_color = color
        self._paused = True

        surviving_color = _other_color(color)
        await self._safe_send(
            self._connections[surviving_color],
            OpponentDisconnectedMessage(grace_seconds=protocol.DISCONNECT_GRACE_SECONDS),
        )
        self._resign_task = asyncio.create_task(self._auto_resign_after_grace(surviving_color))

    async def try_reconnect(self, color: str, new_ws: ServerConnection) -> bool:
        """Called by Matchmaker when a returning username matches a color
        that's currently disconnected in this room - swaps in the new
        connection, resumes the clock, and lets the opponent know.
        Returns False (the caller should fall back to normal
        matchmaking) if the grace period already expired - e.g. a race
        between reconnecting and the auto-resign timer firing."""
        if self._disconnected_color != color:
            return False
        if self._resign_task is not None:
            self._resign_task.cancel()
            self._resign_task = None
        self._connections[color] = new_ws
        self._disconnected_color = None
        self._survivor_also_disconnected = False
        self._paused = False
        self._last_tick = time.perf_counter()  # don't count the paused duration as elapsed game time
        await self._safe_send(self._connections[_other_color(color)], OpponentReconnectedMessage())
        await self._safe_send(new_ws, await self._match_found_message(color))  # so the reconnecting client re-learns its own color/username/rating
        view_state = self._engine.snapshot(move_log=self._move_log.as_dict(), scores=self._score.as_dict())
        await self._safe_send(new_ws, self._personalized_message(color, view_state))  # an immediate board snapshot - the next periodic broadcast is now up to BROADCAST_INTERVAL_SECONDS away, too long to leave a reconnecting client staring at "please wait"
        return True

    async def _handle_select_or_move(self, controller: Controller, message: SelectOrMoveMessage) -> None:
        """Selection feedback (as opposed to an actual move - see
        _broadcast_pending_motions) needs its own immediate, personal
        send: now that BROADCAST_INTERVAL_SECONDS is slow enough to
        matter (section 8), waiting for the next periodic broadcast
        would make a player's own click feel laggy, even though
        nothing about the opponent's view changed."""
        before = (controller.selected_pos, controller.invalid_target)
        controller.handle_cell(Position(message.row, message.col))
        if (controller.selected_pos, controller.invalid_target) != before:
            view_state = self._engine.snapshot(move_log=self._move_log.as_dict(), scores=self._score.as_dict())
            await self._safe_send(
                self._connections[controller.owner_color],
                self._personalized_message(controller.owner_color, view_state),
            )

    async def _handle_jump(self, controller: Controller, message: JumpMessage) -> None:
        controller.handle_jump_cell(Position(message.row, message.col))

    async def _handle_restart(self, controller: Controller, message: RestartMessage) -> None:
        if self._engine.is_game_over():
            self._build_fresh_game()

    async def _handle_resign(self, controller: Controller, message: ResignMessage) -> None:
        """Voluntary forfeit, on demand - the player-triggered
        counterpart to _auto_resign_after_grace's disconnect-timeout
        one. No immediate broadcast - the result shows up on the next
        regular tick, at most BROADCAST_INTERVAL_SECONDS later, same
        as an ordinary cooldown/score change."""
        if self._engine.is_game_over():
            return  # already ended - nothing left to resign from
        resigning_color = controller.owner_color
        winner_color = _other_color(resigning_color)
        logger.info("%s resigned", self._usernames[resigning_color])
        self._engine.resign()
        view_state = self._engine.snapshot(move_log=self._move_log.as_dict(), scores=self._score.as_dict())
        await self._apply_rating_update(view_state, winner_color=winner_color)

    # Dispatch table for in-game messages - one handler per message
    # kind, in place of a growing if/elif isinstance chain. Built from
    # plain (unbound) coroutine functions defined just above, called as
    # await handler(self, controller, message).
    _MESSAGE_HANDLERS: Dict[Type[Any], Callable[["GameRoom", Controller, Any], Awaitable[None]]] = {
        SelectOrMoveMessage: _handle_select_or_move,
        JumpMessage: _handle_jump,
        RestartMessage: _handle_restart,
        ResignMessage: _handle_resign,
    }

    async def handle_message(self, color: str, message: Any) -> None:
        controller = self._controllers[color]
        handler = self._MESSAGE_HANDLERS.get(type(message))
        if handler is not None:
            await handler(self, controller, message)
        await self._broadcast_pending_motions()

    async def _broadcast_pending_motions(self) -> None:
        """Drains whatever MoveLoggedEvents the engine fired while
        handling that one message (usually zero or one) and pushes each
        as an immediate, unthrottled PieceMotionStartedMessage - the
        sparse-event half of section 8's protocol change. Everything
        else an accepted move affects (cooldowns, scores, move log)
        still rides the slower periodic _broadcast; only the moving
        piece itself needs to animate smoothly before that next tick."""
        events, self._motion_collector.events = self._motion_collector.events, []
        if not events:
            return
        recipients = [*self._connections.values(), *self._spectators]
        for event in events:
            message = PieceMotionStartedMessage(event.from_pos, event.to_pos, event.duration_ms)
            await asyncio.gather(*(self._safe_send(ws, message) for ws in recipients))

    async def _run(self) -> None:
        while True:
            await asyncio.sleep(TICK_SECONDS)
            await self._tick_once()

    async def _tick_once(self) -> None:
        """Physics still advances every tick (full precision, unaffected
        by the line below) - only the network send is throttled to
        BROADCAST_INTERVAL_SECONDS, since that's the expensive/chatty
        part, not the math. Events (match_found, disconnect, etc.) are
        separate direct sends elsewhere and are never throttled."""
        now = time.perf_counter()
        dt_ms = int((now - self._last_tick) * 1000)
        self._last_tick = now
        if not self._paused:
            self._engine.wait(dt_ms)
        if now - self._last_broadcast >= BROADCAST_INTERVAL_SECONDS:
            self._last_broadcast = now
            await self._broadcast()

    async def _auto_resign_after_grace(self, surviving_color: str) -> None:
        await asyncio.sleep(protocol.DISCONNECT_GRACE_SECONDS)
        if self._disconnected_color is None:
            return  # already reconnected
        disconnected_username = self._usernames[_other_color(surviving_color)]
        logger.info("auto-resigning %s (disconnect grace period expired)", disconnected_username)
        self._disconnected_color = None
        self._paused = False
        self._engine.resign()
        view_state = self._engine.snapshot(move_log=self._move_log.as_dict(), scores=self._score.as_dict())
        await self._apply_rating_update(view_state, winner_color=surviving_color)
        await self._broadcast()
        if self._survivor_also_disconnected:
            # Nobody is left connected to this room at all - unlike the
            # ordinary auto-resign case (section tested by
            # test_room_name_stays_reserved_after_game_over_...), where
            # the survivor is still around and might click New Game,
            # here there is no one left who ever could. Release it now,
            # the same way leave() does for an explicit "Back to Lobby" -
            # otherwise the tick loop (and, since Stage 3, the
            # GameAllocator's lease-renewal heartbeat) would run forever.
            self.stop()
            if self._on_game_over is not None:
                await self._on_game_over()

    async def _broadcast(self) -> None:
        view_state = self._engine.snapshot(move_log=self._move_log.as_dict(), scores=self._score.as_dict())
        if view_state.game_over:
            await self._apply_rating_update(view_state)
        await asyncio.gather(
            *(
                self._safe_send(ws, self._personalized_message(color, view_state))
                for color, ws in self._connections.items()
            ),
            *(
                self._safe_send(ws, self._spectator_state_message(view_state))
                for ws in self._spectators
            ),
        )

    async def _apply_rating_update(self, view_state: BoardViewState, winner_color: Optional[str] = None) -> None:
        """Runs exactly once per finished game (self-guarding, not just
        relying on the caller to check first). winner_color is only
        passed explicitly for an auto-resign (both kings are still on
        the board, so there's nothing to infer from view_state) -
        otherwise it's the color whose king is still standing. Doesn't
        free the room itself (see leave/on_game_over) - a finished game
        still might get a New Game rematch in the very same room, so
        only actually leaving means the room is truly done."""
        if self._rating_update_applied:
            return
        self._rating_update_applied = True
        if winner_color is None:
            white_has_king = any(p.kind == KING and p.color == WHITE for p in view_state.pieces)
            winner_color = WHITE if white_has_king else BLACK
        loser_color = _other_color(winner_color)
        winner_username, loser_username = self._usernames[winner_color], self._usernames[loser_color]
        old_winner_rating = await self._accounts_client.get_rating(winner_username)
        old_loser_rating = await self._accounts_client.get_rating(loser_username)
        new_winner_rating, new_loser_rating = await self._accounts_client.update_ratings_after_game(
            winner_username, loser_username
        )
        logger.info(
            "rating update: %s %d->%d, %s %d->%d",
            winner_username, old_winner_rating, new_winner_rating,
            loser_username, old_loser_rating, new_loser_rating,
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

    def _spectator_state_message(self, view_state: BoardViewState) -> StateMessage:
        """Same board everyone gets, but no Controller to read a
        personal selection from - a spectator sees the position with no
        highlight of its own."""
        return StateMessage(
            board=view_state,
            your_selected_pos=None,
            your_legal_destinations=set(),
            your_invalid_target=None,
        )

    async def _safe_send(self, ws: ServerConnection, message: Any) -> None:
        try:
            await ws.send(serialize_message(message))
        except Exception as error:
            # a closed/broken socket is handled by the server's own connection loop, not here
            logger.debug("send failed on a closed/broken socket: %s", error)


def _other_color(color: str) -> str:
    return BLACK if color == WHITE else WHITE
