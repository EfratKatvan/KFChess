"""Message "type" constants shared by server and client, so the wire
envelope shape is defined in exactly one place."""

# Login phase (first thing sent/received on a new connection, before matchmaking)
LOGIN = "login"
LOGIN_OK = "login_ok"
LOGIN_FAILED = "login_failed"

# Matchmaking phase (before a player is paired into a GameRoom)
SEEK_GAME = "seek_game"
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

# Room phase (client -> server) - the "Room" button's Create/Join/Cancel dialog
CREATE_ROOM = "create_room"
JOIN_ROOM = "join_room"
CANCEL_ROOM = "cancel_room"

# Room phase (server -> client)
ROOM_CREATED = "room_created"
JOIN_ROOM_FAILED = "join_room_failed"
CREATE_ROOM_FAILED = "create_room_failed"
ROOM_CANCELLED = "room_cancelled"
SPECTATING = "spectating"

MATCHMAKING_TIMEOUT_SECONDS = 60
MATCHMAKING_ELO_RANGE = 100  # a seeker is only matched against another seeker within this many rating points
DISCONNECT_GRACE_SECONDS = 20
MAX_ROOM_ID_LENGTH = 24  # a validation cap on the player-typed room name, not a fixed format
