from __future__ import annotations
from typing import Dict

from kungfu_chess.model.piece import BISHOP, KING, KNIGHT, PAWN, QUEEN, ROOK

PIECE_VALUES: Dict[str, int] = {
    PAWN: 1,
    KNIGHT: 3,
    BISHOP: 3,
    ROOK: 5,
    QUEEN: 9,
    KING: 0,  # לכידת מלך מסיימת את המשחק - אין טעם לנקד אותה
}


def piece_value(kind: str) -> int:
    return PIECE_VALUES[kind]
