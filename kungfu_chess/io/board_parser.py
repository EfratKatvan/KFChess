from __future__ import annotations

from kungfu_chess.model.board import Board
from kungfu_chess.model.piece import Piece, WHITE, BLACK, KING, QUEEN, ROOK, BISHOP, KNIGHT, PAWN
from kungfu_chess.model.position import Position

BOARD_MARKER = "Board:"
COMMANDS_MARKER = "Commands:"
EMPTY_CELL = "."

COLORS = ("w", "b")
PIECE_TYPES = ("K", "Q", "R", "B", "N", "P")

_COLOR_BY_LETTER = {"w": WHITE, "b": BLACK}
_KIND_BY_LETTER = {"K": KING, "Q": QUEEN, "R": ROOK, "B": BISHOP, "N": KNIGHT, "P": PAWN}
_LETTER_BY_COLOR = {color: letter for letter, color in _COLOR_BY_LETTER.items()}
_LETTER_BY_KIND = {kind: letter for letter, kind in _KIND_BY_LETTER.items()}

# ממופה מהטוקן השלם (לא ממיקום-תו בתוכו) - כדי שהמרת טוקן<->כלי לא תניח
# איזה תו מייצג צבע ואיזה סוג-כלי, רק את הטוקן המלא כמפתח.
_PIECE_BY_TOKEN = {
    f"{color_letter}{kind_letter}": (color, kind)
    for color_letter, color in _COLOR_BY_LETTER.items()
    for kind_letter, kind in _KIND_BY_LETTER.items()
}


def build_legal_tokens() -> set[str]:
    tokens = {EMPTY_CELL}
    for color in COLORS:
        for piece in PIECE_TYPES:
            tokens.add(f"{color}{piece}")
    return tokens


def token_to_piece(token: str, position: Position) -> Piece:
    """ממיר טוקן טקסטואלי כמו "wR" לכלי אמיתי במיקום הנתון."""
    color, kind = _PIECE_BY_TOKEN[token]
    return Piece(
        id=f"{token}-{position.row}-{position.col}",
        color=color,
        kind=kind,
        cell=position,
    )


def color_kind_to_token(color: str, kind: str) -> str:
    """בונה טוקן טקסטואלי (כמו "wR") מצבע+סוג-כלי גולמיים, בלי צורך
    ב-Piece שלם - למשל עבור PieceView (ר' engine/board_view_state.py) שלא
    מחזיק אובייקט Piece אמיתי."""
    return f"{_LETTER_BY_COLOR[color]}{_LETTER_BY_KIND[kind]}"


def piece_to_token(piece: Piece) -> str:
    """הכיוון ההפוך - כלי אמיתי בחזרה לטוקן הטקסטואלי שלו."""
    return color_kind_to_token(piece.color, piece.kind)


def build_board(rows: list[list[str]]) -> Board:
    """בונה Board אמיתי (עם Piece לכל תא לא-ריק) משורות טוקסט מאומתות."""
    height = len(rows)
    width = len(rows[0]) if rows else 0
    board = Board(width, height)
    for row_index, row in enumerate(rows):
        for col_index, token in enumerate(row):
            if token == EMPTY_CELL:
                continue
            position = Position(row_index, col_index)
            board.add_piece(token_to_piece(token, position))
    return board


ERROR_ROW_WIDTH_MISMATCH = "ERROR ROW_WIDTH_MISMATCH"
ERROR_UNKNOWN_TOKEN = "ERROR UNKNOWN_TOKEN"


class BoardValidationError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def validate_board(rows: list[list[str]], legal_tokens: set[str]) -> None:
    if not rows:
        return

    width = len(rows[0])
    for row in rows:
        if len(row) != width:
            raise BoardValidationError(ERROR_ROW_WIDTH_MISMATCH)
        for cell in row:
            if cell not in legal_tokens:
                raise BoardValidationError(ERROR_UNKNOWN_TOKEN)


def read_input_lines(stream) -> list[str]:
    return [line.strip() for line in stream.read().splitlines()]


def parse_board_section(lines: list[str]) -> list[list[str]]:
    start = lines.index(BOARD_MARKER) + 1
    rows: list[list[str]] = []
    i = start
    while i < len(lines) and lines[i] != COMMANDS_MARKER:
        if lines[i]:
            rows.append(lines[i].split())
        i += 1
    return rows


def parse_commands_section(lines: list[str]) -> list[str]:
    """מחזירה את שורות הפקודות שמופיעות אחרי המרקר Commands:"""
    if COMMANDS_MARKER not in lines:
        return []
    start = lines.index(COMMANDS_MARKER) + 1
    return [line for line in lines[start:] if line]
