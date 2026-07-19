"""Message "type" constants shared by server and client, so the wire
envelope shape is defined in exactly one place."""

# Matchmaking phase (before a player is paired into a GameRoom)
WAITING_FOR_OPPONENT = "waiting_for_opponent"
NO_OPPONENT_FOUND = "no_opponent_found"
MATCH_FOUND = "match_found"

# In-game phase (client -> server)
SELECT_OR_MOVE = "select_or_move"
JUMP = "jump"
RESTART = "restart"

# In-game phase (server -> client)
STATE = "state"

MATCHMAKING_TIMEOUT_SECONDS = 60
