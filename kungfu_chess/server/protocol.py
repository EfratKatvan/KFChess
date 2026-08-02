"""Message "type" constants shared by server and client, so the wire
envelope shape is defined in exactly one place."""

# Login phase (first thing sent/received on a new connection, before matchmaking)
LOGIN = "login"
REGISTER = "register"  # same shape as LOGIN, but only succeeds for a brand-new username - see accounts.register
TOKEN_LOGIN = "token_login"  # an alternative first message - a saved session token instead of a password (Stage 1b)
LOGIN_OK = "login_ok"
LOGIN_FAILED = "login_failed"

# Lobby phase (client -> server / server -> client) - Stage 1b: revokes the
# current session token, same "grace period" idea section 3 uses for a
# room lease, just for a login session instead
LOGOUT = "logout"
LOGGED_OUT = "logged_out"

# Matchmaking phase (before a player is paired into a GameRoom)
SEEK_GAME = "seek_game"
WAITING_FOR_OPPONENT = "waiting_for_opponent"
NO_OPPONENT_FOUND = "no_opponent_found"
MATCH_FOUND = "match_found"
CANCEL_SEEK = "cancel_seek"  # the Play button's counterpart to CANCEL_ROOM - Back while waiting for an ELO match
SEEK_CANCELLED = "seek_cancelled"

# In-game phase (client -> server)
SELECT_OR_MOVE = "select_or_move"
JUMP = "jump"  # a wire message type, independent of engine/board_view_state.JUMP_STATE
# (a rendering visual-state) - they coincidentally share this literal value but are
# never compared against each other
RESTART = "restart"
RESIGN = "resign"  # forfeits the current game to the opponent on demand - see GameRoom's resign handling

# In-game phase (server -> client)
STATE = "state"
PIECE_MOTION_STARTED = "piece_motion_started"  # sparse, unthrottled - one per accepted move, see Server_Design.md section 8
OPPONENT_DISCONNECTED = "opponent_disconnected"
OPPONENT_RECONNECTED = "opponent_reconnected"

# Post-game-over (client -> server / server -> client) - the "Back to
# Lobby" button, only valid once the game has actually ended
LEAVE_ROOM = "leave_room"
LEFT_ROOM = "left_room"

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
