from __future__ import annotations
from typing import Optional, Tuple

#בודקת האם המסלול מתא היעד לתא המקור פנוי מכלים אחרים עבור הכלים  (מלכה, רץ, צריח)
def is_path_clear(
    board_rows: list[list[str]], from_pos: Tuple[int, int], to_pos: Tuple[int, int]
) -> bool:
    r1, c1 = from_pos
    r2, c2 = to_pos

    dr = r2 - r1
    dc = c2 - c1

    step_r = 0 if dr == 0 else (1 if dr > 0 else -1)
    step_c = 0 if dc == 0 else (1 if dc > 0 else -1)

    curr_r = r1 + step_r
    curr_c = c1 + step_c

    while (curr_r, curr_c) != (r2, c2):
        if board_rows[curr_r][curr_c] != ".":
            return False
        curr_r += step_r
        curr_c += step_c

    return True


def is_legal_pawn_move(
    color: str,
    from_pos: Tuple[int, int],
    to_pos: Tuple[int, int],
    board_rows: list[list[str]],
    target_token: str,
) -> bool:
    r1, c1 = from_pos
    r2, c2 = to_pos
    board_height = len(board_rows)

    if color == "w":
        direction = -1
        start_row = board_height - 2 if board_height == 8 else board_height - 1
    else:
        direction = 1
        start_row = 1 if board_height == 8 else 0

    if c1 == c2:
        if r2 - r1 == direction and target_token == ".":
            return True
        if r1 == start_row and r2 - r1 == 2 * direction:
            mid_r = r1 + direction
            if board_rows[mid_r][c1] == "." and target_token == ".":
                return True

    if abs(c2 - c1) == 1 and r2 - r1 == direction:
        if target_token != "." and target_token[0] != color:
            return True

    return False


def is_legal_piece_move(
    piece: str,
    from_pos: Tuple[int, int],
    to_pos: Tuple[int, int],
    board_rows: Optional[list[list[str]]] = None,
    target_token: str = ".",
) -> bool:
    if piece == ".":
        return False

    color = piece[0]
    p_type = piece[1]

    r1, c1 = from_pos
    r2, c2 = to_pos
    # אם המקור והיעד זהים, אין תנועה חוקית
    if r1 == r2 and c1 == c2:
        return False

    dr = abs(r2 - r1)
    dc = abs(c2 - c1)
    #מנסה לאכול מישהו מהקבוצה שלו-בצבע שלו
    if target_token != "." and target_token[0] == color:
        return False
    #אם זה מלך, הוא יכול לזוז רק תא אחד לכל כיוון
    if p_type == "K":
        return dr <= 1 and dc <= 1
    #אם זה צריח, הוא יכול לזוז רק ישר בעמודות או בשורות, ואם רוצה יותר ממקום אחד, הוא צריך לבדוק שהמסלול פנוי
    if p_type == "R":
        if r1 != r2 and c1 != c2:
            return False
        if board_rows is not None and not is_path_clear(board_rows, from_pos, to_pos):
            return False
        return True
    #אם זה רץ, הוא יכול לזוז רק באלכסון, ואם רוצה יותר ממקום אחד, הוא צריך לבדוק שהמסלול פנוי
    if p_type == "B":
        if dr != dc:
            return False
        if board_rows is not None and not is_path_clear(board_rows, from_pos, to_pos):
            return False
        return True
    #אם זה מלכה, הוא יכול לזוז ישר או באלכסון, ואם רוצה יותר ממקום אחד, הוא צריך לבדוק שהמסלול פנוי
    if p_type == "Q":
        is_straight = (r1 == r2) or (c1 == c2)
        is_diagonal = dr == dc
        if not (is_straight or is_diagonal):
            return False
        if board_rows is not None and not is_path_clear(board_rows, from_pos, to_pos):
            return False
        return True
    #אם זה סוס, הוא יכול לזוז רק בתבנית של "L" (שני צעדים בכיוון אחד ואחריו צעד אחד בכיוון מאונך)
    if p_type == "N":
        return (dr == 1 and dc == 2) or (dr == 2 and dc == 1)
    #אם זה חייל, הוא יכול לזוז רק קדימה (לפי צבעו) או לאכול באלכסון, ואם הוא רוצה לזוז יותר ממקום אחד קדימה, הוא צריך לבדוק שהמסלול פנוי
    if p_type == "P":
        if board_rows is None:
            return False
        return is_legal_pawn_move(color, from_pos, to_pos, board_rows, target_token)

    return False
