"""Configuration, all driven from environment variables.

Everything has a sensible default so the app runs out of the box for local
poking. The two you must set in production are SECRET_KEY and ANTHROPIC_API_KEY.
"""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("CC_DATA_DIR", BASE_DIR / "data"))
PHOTO_DIR = DATA_DIR / "photos"
DB_PATH = DATA_DIR / "captains_log.db"

SECRET_KEY = os.environ.get("CC_SECRET_KEY", "dev-only-change-me")

# Seed account, only used the very first time the database is created.
INITIAL_USER = os.environ.get("CC_INITIAL_USER", "dave")
INITIAL_PASSWORD = os.environ.get("CC_INITIAL_PASSWORD", "")

# Anthropic API, used for reading photographed scoresheets.
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = os.environ.get("CC_MODEL", "claude-sonnet-5")
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"

# Photos get downscaled before upload. Phone cameras produce 3-5 MB files and
# the API caps a single image at 5 MB base64, so this is both a cost and a
# correctness measure.
MAX_IMAGE_EDGE = int(os.environ.get("CC_MAX_IMAGE_EDGE", "1568"))
MAX_UPLOAD_BYTES = int(os.environ.get("CC_MAX_UPLOAD_BYTES", str(15 * 1024 * 1024)))

PAGE_SIZE = 20

DIFFICULTIES = ["Cadet", "Ensign", "Lieutenant", "Commander", "Captain", "Admiral"]

# At Cadet there is no opposing bot. There is no opponent captain and no bot
# column; instead you win by reaching a target score.
SOLO_RANK = "Cadet"

# Used where a rank has to fit a narrow column.
RANK_SHORT = {
    "Cadet": "Cadet",
    "Ensign": "Ensign",
    "Lieutenant": "Lt",
    "Commander": "Cmdr",
    "Captain": "Capt",
    "Admiral": "Adm",
}
SOLO_WIN_SCORE = int(os.environ.get("CC_SOLO_WIN_SCORE", "70"))

# The eight scoring rows, in the order they appear on the printed pad.
# key, label, whether the bot can score it, and the swatch colour that matches
# the paper sheet.
SCORE_ROWS = [
    ("glory", "Glory", True, "#B4B2A9"),
    ("locations", "Neutral locations", True, "#5DCAA5"),
    ("endgame", "Endgame ops", True, "#F0997B"),
    ("card_vp", "Card VP", True, "#85B7EB"),
    ("research", "Research focus", True, "#378ADD"),
    ("influence", "Influence focus", True, "#EF9F27"),
    ("military", "Military focus", True, "#F09595"),
    ("mission", "Mission", False, "#AFA9EC"),
]

SCORE_KEYS = [key for key, _, _, _ in SCORE_ROWS]
BOT_SCORE_KEYS = [key for key, _, bot, _ in SCORE_ROWS if bot]
