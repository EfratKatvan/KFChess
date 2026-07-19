from __future__ import annotations
from typing import Optional

from kungfu_chess.model.position import Position
from kungfu_chess.input.board_mapper import BoardMapper
from kungfu_chess.engine.game_engine import GameEngine, REASON_DESTINATION_RESERVED


class Controller:
    """Interprets clicks and owns only the selection/interaction state
    (selected_pos, invalid_target). Doesn't hold a Board, doesn't check
    chess legality, and never touches the board - every question about
    game state is an explicit call to GameEngine (the service), not a
    direct board read."""

    def __init__(self, mapper: Optional[BoardMapper], engine: GameEngine, owner_color: Optional[str] = None) -> None:
        """owner_color restricts which color this Controller may select a
        new piece of - None (the default) keeps today's single-player
        behavior where any click can act on any color. Set for a
        networked player so one connection can't move the opponent's
        pieces (see kungfu_chess/server/game_room.py)."""
        self._mapper = mapper
        self._engine = engine
        self._owner_color = owner_color
        self.selected_pos: Optional[Position] = None
        self.invalid_target: Optional[Position] = None

    def handle_click(self, x: int, y: int) -> None:
        cell = self._mapper.to_cell(x, y)
        if cell is None:
            return
        self.handle_cell(cell)

    def handle_cell(self, cell: Position) -> None:
        self.invalid_target = None

        # (can_select already covers the game_over check - no need to check it again here)
        if self.selected_pos is None:
            if self._owner_color is not None and self._engine.color_at(cell) != self._owner_color:
                return
            if self._engine.can_select(cell):
                self.selected_pos = cell
            return
        if self.selected_pos == cell:
            return

        if self._engine.is_same_color(self.selected_pos, cell):
            if self._engine.can_select(cell):
                self.selected_pos = cell
            return

        # game_over and move legality are both checked inside request_move - single gate
        result = self._engine.request_move(self.selected_pos, cell)
        if result.is_accepted or result.reason == REASON_DESTINATION_RESERVED:
            self.selected_pos = None
        else:
            self.invalid_target = cell

    def handle_jump(self, x: int, y: int) -> None:
        cell = self._mapper.to_cell(x, y)
        if cell is None:
            return
        self.handle_jump_cell(cell)

    def handle_jump_cell(self, cell: Position) -> None:
        if self._owner_color is not None and self._engine.color_at(cell) != self._owner_color:
            return
        # game_over is checked inside try_jump - single gate
        self._engine.try_jump(cell)
