"""Message "type" constants shared by server and client, so the wire
envelope shape is defined in exactly one place."""

# Login phase (first thing sent/received on a new connection, before matchmaking)
LOGIN = "login"
LOGIN_OK = "login_ok"
LOGIN_FAILED = "login_failed"

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
OPPONENT_DISCONNECTED = "opponent_disconnected"
OPPONENT_RECONNECTED = "opponent_reconnected"

MATCHMAKING_TIMEOUT_SECONDS = 60
DISCONNECT_GRACE_SECONDS = 20
