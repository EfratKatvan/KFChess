# Git repo: https://github.com/EfratKatvan/KFChess.git
from __future__ import annotations

from kungfu_chess.engine.game_engine import GameEngine
from kungfu_chess.input.board_mapper import BoardMapper
from kungfu_chess.input.controller import Controller
from kungfu_chess.io.board_parser import build_board
from kungfu_chess.realtime.real_time_arbiter import RealTimeArbiter
from kungfu_chess.rules.rule_engine import RuleEngine
from kungfu_chess.view import image_view

# בחירת חבילת הגרפיקה - "pieces1" (נכסי-פיתוח, ללא alpha אמיתי) או
# "pieces2" (אמנות סופית עם שקיפות אמיתית - ברירת המחדל). ר' view/renderer.py.
PIECE_SET = "pieces2"

STARTING_POSITION = [
    ["bR", "bN", "bB", "bQ", "bK", "bB", "bN", "bR"],
    ["bP", "bP", "bP", "bP", "bP", "bP", "bP", "bP"],
    [".", ".", ".", ".", ".", ".", ".", "."],
    [".", ".", ".", ".", ".", ".", ".", "."],
    [".", ".", ".", ".", ".", ".", ".", "."],
    [".", ".", ".", ".", ".", ".", ".", "."],
    ["wP", "wP", "wP", "wP", "wP", "wP", "wP", "wP"],
    ["wR", "wN", "wB", "wQ", "wK", "wB", "wN", "wR"],
]


def main() -> None:
    board = build_board(STARTING_POSITION)
    rule_engine = RuleEngine(board)
    arbiter = RealTimeArbiter(board)
    engine = GameEngine(board, rule_engine, arbiter)
    mapper = BoardMapper(board)
    controller = Controller(mapper, engine)

    image_view.run(engine, controller, piece_set=PIECE_SET)


if __name__ == "__main__":
    main()
