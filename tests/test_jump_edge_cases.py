import pytest
from board.model import Board
from game.controller import GameController


def test_jump_airborne_captures_arriving_enemy():
    """טסט 1: כלי קופץ באוויר בולם כלי אויב שמגיע לתאו ומעלים אותו."""
    board = Board.from_rows([
        [".", ".", "."],
        ["wK", "bR", "."],
        [".", ".", "."]
    ])
    controller = GameController(board)

    # wK קופץ (תופס את ה-1000ms הקרובים)
    controller.execute_command("jump 50 150")      # (1,0)
    # bR נע לכיוון (1,0) - מרחק 1 לוקח 1000ms
    controller.execute_command("click 150 150")     # (1,1)
    controller.execute_command("click 50 150")      # (1,0)
    controller.execute_command("wait 1000")

    # bR אמור להיאכל ולהיעלם, wK נשאר במקומו
    assert board._rows[1] == ["wK", ".", "."]
    assert controller.game_over is False


def test_jump_too_late_does_not_save_piece():
    """טסט 2: כלי שלא קפץ בזמן ונאכל - פקודת jump מאוחרת עליו מבוטלת/לא משפיעה."""
    board = Board.from_rows([
        [".", ".", "."],
        ["wK", "bR", "."],
        [".", ".", "."]
    ])
    controller = GameController(board)

    # bR נע ל-(1,0) ונכנס תוך 1000ms
    controller.execute_command("click 150 150")     # (1,1)
    controller.execute_command("click 50 150")      # (1,0)
    controller.execute_command("wait 1000")

    # ניסיון לבצע jump על wK שכבר נאכל
    controller.execute_command("jump 50 150")

    # bR תפס את המשבצת, wK נעלם, המשחק הסתיים
    assert board._rows[1] == ["bR", ".", "."]
    assert controller.game_over is True


def test_enemy_arrives_after_landing_captures_normally():
    """טסט 3: אויב שמגיע לאחר שהקפיצה הסתיימה (נחיתה) אוכל את הכלי נורמלית."""
    board = Board.from_rows([
        [".", ".", ".", "."],
        ["wK", ".", ".", "bR"],
        [".", ".", ".", "."]
    ])
    controller = GameController(board)

    # wK קופץ ב-t=0 (קפיצה תסתיים ב-t=1000)
    controller.execute_command("jump 50 150")
    controller.execute_command("wait 1000")         # הקפיצה הסתיימה!

    # bR מ-(1,3) נע ל-(1,0) - מרחק 3 לוקח 3000ms
    controller.execute_command("click 350 150")
    controller.execute_command("click 50 150")
    controller.execute_command("wait 3000")

    # bR אכל את wK בנחיתה
    assert board._rows[1] == ["bR", ".", ".", "."]
    assert controller.game_over is True


def test_cannot_jump_while_moving():
    """טסט 4: כלי שנמצא בתנועה אינו יכול לקפוץ."""
    board = Board.from_rows([
        ["wR", ".", "."]
    ])
    controller = GameController(board)

    # wR מתחיל תנועה מ-(0,0) ל-(0,2)
    controller.execute_command("click 50 50")
    controller.execute_command("click 250 50")

    # ניסיון לקפוץ תוך כדי תנועה
    controller.execute_command("jump 50 50")
    assert len(controller.jumping_pieces) == 0


def test_cannot_jump_empty_cell():
    """טסט 5: ניסיון לבצע jump על משבצת ריקה נכשל."""
    board = Board.from_rows([
        [".", ".", "."]
    ])
    controller = GameController(board)

    controller.execute_command("jump 50 50")
    assert len(controller.jumping_pieces) == 0


def test_multiple_wait_increments_during_jump():
    """טסט 6: בדיקת קפיצה לאורך מספר פקודות wait קטנות (למשל wait 400 + wait 400 + wait 400)."""
    board = Board.from_rows([
        [".", ".", "."],
        ["wK", "bR", "."],
        [".", ".", "."]
    ])
    controller = GameController(board)

    controller.execute_command("jump 50 150")  # קפיצה ל-1000ms
    controller.execute_command("click 150 150")
    controller.execute_command("click 50 150")  # תנועה לוקחת 1000ms

    controller.execute_command("wait 400")      # נשארו 600ms לקפיצה ולתנועה
    controller.execute_command("wait 400")      # נשארו 200ms לקפיצה ולתנועה
    assert board._rows[1] == ["wK", "bR", "."]  # bR עדיין בדרך

    controller.execute_command("wait 400")      # הזמן תם (1200ms סה"כ) -> bR הגיע בזמן שהיה באוויר ונלכד
    assert board._rows[1] == ["wK", ".", "."]


def test_no_commands_after_game_over():
    """טסט 7: פקודות click ו-jump מבוטלות לאחר שהמשחק הסתיים (game_over)."""
    board = Board.from_rows([
        ["wK", "bR"]
    ])
    controller = GameController(board)

    # bR אוכל את wK
    controller.execute_command("click 150 50")
    controller.execute_command("click 50 50")
    controller.execute_command("wait 1000")

    assert controller.game_over is True

    # ניסיונות לבצע פעולות נוספות לאחר הפסד
    controller.execute_command("jump 50 50")
    controller.execute_command("click 50 50")

    assert len(controller.jumping_pieces) == 0
    assert len(controller.moving_pieces) == 0