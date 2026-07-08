import sys
from board import parse_board, validate_board
from pieces import can_move, path_still_clear


lines = [line.strip() for line in sys.stdin.read().splitlines()]


if "Board:" not in lines:
    sys.exit()


board = parse_board(lines)

validate_board(board)


rows = len(board)
cols = len(board[0]) if rows else 0


selected = None
moving_pieces = []


if "Commands:" in lines:

    i = lines.index("Commands:") + 1

    while i < len(lines):

        cmd = lines[i].split()

        if not cmd:
            i += 1
            continue


        if cmd[0] == "click":

            x = int(cmd[1])
            y = int(cmd[2])


            if x < 0 or y < 0:
                i += 1
                continue


            c = x // 100
            r = y // 100


            if r < 0 or r >= rows or c < 0 or c >= cols:
                i += 1
                continue


            cell = board[r][c]


            if moving_pieces:

                moving_sources = {
                    (msr, msc)
                    for (_, msr, msc, _, _, _) in moving_pieces
                }


                # אי אפשר לבחור כלי שכבר בתנועה
                if selected is None and (r, c) in moving_sources:
                    i += 1
                    continue


                if selected is not None:
                    sr, sc = selected

                    if (sr, sc) in moving_sources:
                        i += 1
                        continue



            if selected is None:

                if cell != ".":
                    selected = (r, c)



            else:

                sr, sc = selected
                piece = board[sr][sc]


                if cell != "." and cell[0] == piece[0]:

                    selected = (r, c)


                else:

                    if can_move(board, piece, sr, sc, r, c):

                        distance = max(abs(r - sr), abs(c - sc))

                        moving_pieces.append(
                            (piece, sr, sc, r, c, distance * 1000)
                        )

                        selected = None



        elif cmd[0] == "print" and len(cmd) > 1 and cmd[1] == "board":

            for row in board:
                print(" ".join(row))



        elif cmd[0] == "wait":

            t = int(cmd[1])


            if moving_pieces:


                # מי מגיע בזמן הזה
                arriving = []

                for index, (piece, sr, sc, r, c, remaining) in enumerate(moving_pieces):
                    if remaining - t <= 0:
                        arriving.append(
                            (piece, sr, sc, r, c, index)
                        )


                new_moving = []


                for piece, sr, sc, r, c, remaining in moving_pieces:


                    remaining -= t


                    if remaining <= 0:


                        # בדיקת התנגשות אויבים
                        collision = False


                        for other_piece, osr, osc, orow, ocol, other_index in arriving:


                            if other_piece != piece:

                                if orow == r and ocol == c:

                                    my_index = None

                            for index, move in enumerate(moving_pieces):
                                if move == (piece, sr, sc, r, c, remaining + t):
                                    my_index = index
                                    break
                                
                                
                            if my_index > other_index:
                                collision = True



                            if collision:
                                continue
                                                    


                        # חסימה דינמית
                        if piece[1] in ['R', 'B', 'Q']:

                            if not path_still_clear(board, sr, sc, r, c):
                                continue



                        target = board[r][c]


                        # אי אפשר לנחות על כלי ידידותי
                        if target != "." and target[0] == piece[0]:

                            pass


                        else:

                            board[r][c] = piece


                            if board[sr][sc] == piece:
                                board[sr][sc] = "."



                    else:

                        new_moving.append(
                            (piece, sr, sc, r, c, remaining)
                        )


                moving_pieces = new_moving


        i += 1