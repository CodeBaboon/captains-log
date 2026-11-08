"""SQLite access layer.

Plain sqlite3, no ORM. The schema is small and fixed, and keeping the
dependency list short matters on a Pi 3.
"""

import sqlite3
from datetime import datetime, timezone

from werkzeug.security import generate_password_hash

import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY,
    username      TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    is_admin      INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS captains (
    id     INTEGER PRIMARY KEY,
    name   TEXT NOT NULL UNIQUE,
    box    TEXT NOT NULL DEFAULT 'Other',
    active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS games (
    id             INTEGER PRIMARY KEY,
    user_id        INTEGER NOT NULL REFERENCES users(id),
    played_on      TEXT NOT NULL,
    player_captain TEXT NOT NULL,
    board_side     TEXT NOT NULL,
    bot_captain    TEXT NOT NULL,
    bot_difficulty TEXT NOT NULL,
    ending         TEXT NOT NULL,
    result         TEXT NOT NULL,

    p_glory     INTEGER, b_glory     INTEGER,
    p_locations INTEGER, b_locations INTEGER,
    p_endgame   INTEGER, b_endgame   INTEGER,
    p_card_vp   INTEGER, b_card_vp   INTEGER,
    p_research  INTEGER, b_research  INTEGER,
    p_influence INTEGER, b_influence INTEGER,
    p_military  INTEGER, b_military  INTEGER,
    p_mission   INTEGER,

    p_total    INTEGER,
    b_total    INTEGER,
    photo_path TEXT,
    notes      TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_games_user_date
    ON games (user_id, played_on DESC, id DESC);
"""

# Captains I could confirm. Add the rest from the New game screen as you meet
# them, they get saved automatically.
SEED_CAPTAINS = [
    ("Kirk", "To Boldly Go"),
    ("Khan", "To Boldly Go"),
    ("Georgiou", "To Boldly Go"),
    ("Rebner", "To Boldly Go"),
    ("Soval", "To Boldly Go"),
    ("Picard", "Captain's Chair"),
    ("Sisko", "Captain's Chair"),
    ("Burnham", "Captain's Chair"),
    ("Koloth", "Captain's Chair"),
    ("Sela", "Captain's Chair"),
    ("Shran", "Captain's Chair"),
]


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect():
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def _migrate(conn):
    """Small, idempotent schema additions for databases created earlier."""
    columns = {r["name"] for r in conn.execute("PRAGMA table_info(users)")}
    if "is_admin" not in columns:
        conn.execute("ALTER TABLE users ADD COLUMN is_admin INTEGER NOT NULL DEFAULT 0")
        # The original account becomes the administrator.
        conn.execute(
            "UPDATE users SET is_admin = 1 "
            "WHERE id = (SELECT MIN(id) FROM users)"
        )


def init_db():
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    config.PHOTO_DIR.mkdir(parents=True, exist_ok=True)

    conn = connect()
    with conn:
        conn.executescript(SCHEMA)
        _migrate(conn)
        for name, box in SEED_CAPTAINS:
            conn.execute(
                "INSERT OR IGNORE INTO captains (name, box) VALUES (?, ?)",
                (name, box),
            )

        existing = conn.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"]
        if existing == 0 and config.INITIAL_PASSWORD:
            conn.execute(
                "INSERT INTO users (username, password_hash, is_admin, created_at) "
                "VALUES (?, ?, 1, ?)",
                (
                    config.INITIAL_USER,
                    generate_password_hash(config.INITIAL_PASSWORD),
                    now_iso(),
                ),
            )
    conn.close()


def get_user_by_name(username):
    conn = connect()
    row = conn.execute(
        "SELECT * FROM users WHERE username = ?", (username,)
    ).fetchone()
    conn.close()
    return row


def get_user(user_id):
    conn = connect()
    row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    conn.close()
    return row


def user_count():
    conn = connect()
    n = conn.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"]
    conn.close()
    return n


def create_user(username, password, is_admin=None):
    """Create an account. The first one ever made administers the captain list."""
    conn = connect()
    with conn:
        if is_admin is None:
            existing = conn.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"]
            is_admin = existing == 0
        cur = conn.execute(
            "INSERT INTO users (username, password_hash, is_admin, created_at) "
            "VALUES (?, ?, ?, ?)",
            (username, generate_password_hash(password), 1 if is_admin else 0, now_iso()),
        )
    conn.close()
    return cur.lastrowid


def list_captains(include_retired=False):
    """Captains available to pick. Retired ones are hidden unless asked for."""
    where = "" if include_retired else "WHERE active = 1"
    conn = connect()
    rows = conn.execute(
        f"SELECT id, name, box, active FROM captains {where} ORDER BY box, name"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def captain_usage():
    """How many games reference each captain name, across both columns.

    Used by the admin page to show what a change would affect, and to decide
    whether a captain can be deleted outright.
    """
    conn = connect()
    rows = conn.execute(
        """
        SELECT name, SUM(n) AS games FROM (
            SELECT player_captain AS name, COUNT(*) AS n FROM games
             WHERE player_captain != '' GROUP BY player_captain
            UNION ALL
            SELECT bot_captain AS name, COUNT(*) AS n FROM games
             WHERE bot_captain != '' GROUP BY bot_captain
        ) GROUP BY name COLLATE NOCASE
        """
    ).fetchall()
    conn.close()
    return {r["name"]: r["games"] for r in rows}


def get_captain(captain_id):
    conn = connect()
    row = conn.execute(
        "SELECT id, name, box, active FROM captains WHERE id = ?", (captain_id,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def rename_captain(captain_id, new_name, box=None):
    """Rename a captain and carry every game it appears in along with it.

    Games store captain names as text, so a rename that did not cascade would
    orphan the history under the old spelling.
    """
    new_name = (new_name or "").strip()
    if not new_name:
        raise ValueError("A captain needs a name.")
    if len(new_name) > 60:
        raise ValueError("That name is too long.")

    current = get_captain(captain_id)
    if current is None:
        raise ValueError("No such captain.")

    conn = connect()
    try:
        clash = conn.execute(
            "SELECT id FROM captains WHERE name = ? COLLATE NOCASE AND id != ?",
            (new_name, captain_id),
        ).fetchone()
        if clash:
            raise ValueError(f"{new_name} is already on the list.")

        with conn:
            conn.execute(
                "UPDATE captains SET name = ?, box = COALESCE(?, box) WHERE id = ?",
                (new_name, box if box in BOXES else None, captain_id),
            )
            if new_name != current["name"]:
                conn.execute(
                    "UPDATE games SET player_captain = ? WHERE player_captain = ?",
                    (new_name, current["name"]),
                )
                conn.execute(
                    "UPDATE games SET bot_captain = ? WHERE bot_captain = ?",
                    (new_name, current["name"]),
                )
    finally:
        conn.close()
    return new_name


def set_captain_active(captain_id, active):
    """Retire or restore a captain.

    Retiring hides it from new games but leaves history intact and keeps it
    selectable when editing a game that already uses it.
    """
    conn = connect()
    with conn:
        conn.execute(
            "UPDATE captains SET active = ? WHERE id = ?",
            (1 if active else 0, captain_id),
        )
    conn.close()


def delete_captain(captain_id):
    """Remove a captain outright. Refused while any game still references it."""
    captain = get_captain(captain_id)
    if captain is None:
        raise ValueError("No such captain.")

    used = captain_usage().get(captain["name"], 0)
    if used:
        raise ValueError(
            f"{captain['name']} is used by {used} game"
            f"{'' if used == 1 else 's'}. Retire it instead."
        )

    conn = connect()
    with conn:
        conn.execute("DELETE FROM captains WHERE id = ?", (captain_id,))
    conn.close()


BOXES = ["To Boldly Go", "Captain's Chair", "Expansion", "Other"]


def captain_exists(name):
    """Case-insensitive lookup. Returns the stored spelling, or None.

    Retired captains still count. A game logged before a captain was retired
    has to stay editable.
    """
    name = (name or "").strip()
    if not name:
        return None
    conn = connect()
    row = conn.execute(
        "SELECT name FROM captains WHERE name = ? COLLATE NOCASE",
        (name,),
    ).fetchone()
    conn.close()
    return row["name"] if row else None


def add_captain(name, box="Other"):
    """Register a captain. Returns the stored spelling.

    If one already exists under a different capitalisation, that spelling wins,
    so 'georgiou' can never become a second Georgiou.
    """
    name = (name or "").strip()
    if not name:
        return None

    existing = captain_exists(name)
    if existing:
        return existing

    if box not in BOXES:
        box = "Other"
    conn = connect()
    with conn:
        conn.execute(
            "INSERT OR IGNORE INTO captains (name, box) VALUES (?, ?)", (name, box)
        )
    conn.close()
    return name


GAME_FIELDS = (
    ["user_id", "played_on", "player_captain", "board_side", "bot_captain",
     "bot_difficulty", "ending", "result"]
    + [f"p_{k}" for k in config.SCORE_KEYS]
    + [f"b_{k}" for k in config.BOT_SCORE_KEYS]
    + ["p_total", "b_total", "photo_path", "notes", "created_at"]
)


def insert_game(data):
    values = [data.get(f) for f in GAME_FIELDS]
    placeholders = ", ".join("?" for _ in GAME_FIELDS)
    conn = connect()
    with conn:
        cur = conn.execute(
            f"INSERT INTO games ({', '.join(GAME_FIELDS)}) VALUES ({placeholders})",
            values,
        )
    conn.close()
    return cur.lastrowid


def update_game(game_id, user_id, data):
    fields = [f for f in GAME_FIELDS if f not in ("user_id", "created_at")]
    assignments = ", ".join(f"{f} = ?" for f in fields)
    values = [data.get(f) for f in fields] + [game_id, user_id]
    conn = connect()
    with conn:
        conn.execute(
            f"UPDATE games SET {assignments} WHERE id = ? AND user_id = ?", values
        )
    conn.close()


def get_game(game_id, user_id):
    conn = connect()
    row = conn.execute(
        "SELECT * FROM games WHERE id = ? AND user_id = ?", (game_id, user_id)
    ).fetchone()
    conn.close()
    return row


def delete_game(game_id, user_id):
    conn = connect()
    with conn:
        row = conn.execute(
            "SELECT photo_path FROM games WHERE id = ? AND user_id = ?",
            (game_id, user_id),
        ).fetchone()
        conn.execute(
            "DELETE FROM games WHERE id = ? AND user_id = ?", (game_id, user_id)
        )
    conn.close()
    return row["photo_path"] if row else None


def list_games(user_id, limit=config.PAGE_SIZE, offset=0):
    conn = connect()
    rows = conn.execute(
        "SELECT * FROM games WHERE user_id = ? "
        "ORDER BY played_on DESC, id DESC LIMIT ? OFFSET ?",
        (user_id, limit, offset),
    ).fetchall()
    conn.close()
    return rows


def count_games(user_id):
    conn = connect()
    n = conn.execute(
        "SELECT COUNT(*) AS n FROM games WHERE user_id = ?", (user_id,)
    ).fetchone()["n"]
    conn.close()
    return n


def captain_counts(user_id, field="player_captain"):
    """How many games each captain appears in, for the filter panel."""
    if field not in ("player_captain", "bot_captain"):
        raise ValueError("bad field")
    conn = connect()
    rows = conn.execute(
        f"SELECT {field} AS name, COUNT(*) AS n FROM games "
        f"WHERE user_id = ? AND {field} != '' GROUP BY {field}",
        (user_id,),
    ).fetchall()
    conn.close()
    return {r["name"]: r["n"] for r in rows}


def filtered_games(user_id, perspective="you", captains=None, boards=None, ranks=None):
    """Games matching the stats page filters.

    An empty selection in any group means "no filter" rather than "nothing",
    so clearing a group cannot strand you on an empty page.
    """
    where = ["user_id = ?"]
    params = [user_id]

    if perspective == "bot":
        # Cadet games have no opponent, so they cannot appear from the bot's side.
        where.append("bot_captain != ''")

    if captains:
        field = "player_captain" if perspective == "you" else "bot_captain"
        where.append(
            f"{field} IN ({', '.join('?' for _ in captains)}) COLLATE NOCASE"
        )
        params.extend(captains)

    if boards:
        where.append(f"board_side IN ({', '.join('?' for _ in boards)})")
        params.extend(boards)

    if ranks:
        where.append(f"bot_difficulty IN ({', '.join('?' for _ in ranks)})")
        params.extend(ranks)

    conn = connect()
    rows = conn.execute(
        f"SELECT * FROM games WHERE {' AND '.join(where)} "
        "ORDER BY played_on DESC, id DESC",
        params,
    ).fetchall()
    conn.close()
    return rows


def stats(user_id):
    """Headline numbers for the log screen.

    Average points deliberately excludes Burn games, which have no score.
    """
    conn = connect()
    row = conn.execute(
        """
        SELECT
            COUNT(*) AS games,
            SUM(CASE WHEN result = 'win' THEN 1 ELSE 0 END) AS wins,
            AVG(CASE WHEN ending = 'resolution' THEN p_total END) AS avg_points
        FROM games WHERE user_id = ?
        """,
        (user_id,),
    ).fetchone()
    conn.close()
    avg = row["avg_points"]
    return {
        "games": row["games"] or 0,
        "wins": row["wins"] or 0,
        "avg_points": round(avg) if avg is not None else None,
    }
