# Git repo: https://github.com/EfratKatvan/KFChess.git
from __future__ import annotations

from kungfu_chess.server.server import HOST, PORT
from kungfu_chess.starting_position import STARTING_POSITION
from kungfu_chess.view import image_view, network_client_view


PIECE_SET = "pieces3"
SERVER_URI = f"ws://{HOST}:{PORT}"


def main() -> None:
    board_width, board_height = len(STARTING_POSITION[0]), len(STARTING_POSITION)
    cell_size = image_view.compute_cell_size(board_width, board_height)
    network_client_view.run_client(SERVER_URI, cell_size=cell_size, piece_set=PIECE_SET)


if __name__ == "__main__":
    main()
