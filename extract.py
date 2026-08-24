"""Read a photographed scoresheet into structured data.

The heavy lifting happens at the API, so this runs fine on a Pi. All we do
locally is downscale the image and validate what comes back.
"""

import base64
import io
import json
import re

import requests

import config

try:
    from PIL import Image

    HAVE_PILLOW = True
except ImportError:  # pragma: no cover - Pillow is strongly recommended
    HAVE_PILLOW = False


class ExtractionError(Exception):
    pass


PROMPT = """You are reading a photograph of a handwritten scorepad for the board game
Star Trek: Captain's Chair. Return ONLY a JSON object, no prose, no markdown fences.

The pad has a fixed layout. Two score columns: the left is the human player,
the right is the solo bot. The player's captain name is handwritten at the top of
the left column; the bot's captain name at the top of the right column. Above the
bot's captain name the word "BOT" may appear, and above or beside that a
difficulty word: Cadet, Ensign, Lieutenant, Commander, Captain, or Admiral.

If the player's captain name is followed by "(ADV.)", "ADV", or "Advanced",
the player used the Advanced side of their board. Otherwise assume Basic.

At the Cadet rank there is no opposing bot at all. If the right-hand column is
entirely blank, has no captain name, or is struck through, set bot_captain to
null, set every value in "bot" to null, and set bot_difficulty to "Cadet" only
if the word Cadet actually appears. Do not invent a rank that is not written.

The eight score rows, top to bottom, always in this order:
1. glory
2. locations
3. endgame
4. card_vp        (this row can legitimately be negative)
5. research
6. influence
7. military
8. mission        (the bot NEVER scores this row)

Handwriting notes: a zero may be written slashed, as a circle with a diagonal
line through it. A diagonal line alone filling a cell means "not applicable",
which is normal for the bot's mission row. Read a leading minus sign as a
negative number.

Return exactly this shape. Use null for anything you cannot read confidently.
Do not guess. Numbers must be integers, not strings.

{
  "player_captain": "string or null",
  "bot_captain": "string or null",
  "board_side": "basic" | "advanced" | null,
  "bot_difficulty": "Cadet"|"Ensign"|"Lieutenant"|"Commander"|"Captain"|"Admiral"|null,
  "player": {
    "glory": int|null, "locations": int|null, "endgame": int|null,
    "card_vp": int|null, "research": int|null, "influence": int|null,
    "military": int|null, "mission": int|null
  },
  "bot": {
    "glory": int|null, "locations": int|null, "endgame": int|null,
    "card_vp": int|null, "research": int|null, "influence": int|null,
    "military": int|null
  },
  "player_total_written": int|null,
  "bot_total_written": int|null
}"""


def prepare_image(raw_bytes, content_type="image/jpeg"):
    """Downscale and re-encode so we stay well under the API's size cap."""
    if not HAVE_PILLOW:
        return base64.b64encode(raw_bytes).decode("ascii"), content_type

    img = Image.open(io.BytesIO(raw_bytes))

    # Phone photos carry EXIF rotation that PIL ignores unless asked.
    try:
        from PIL import ImageOps

        img = ImageOps.exif_transpose(img)
    except Exception:
        pass

    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")

    longest = max(img.size)
    if longest > config.MAX_IMAGE_EDGE:
        scale = config.MAX_IMAGE_EDGE / longest
        img = img.resize(
            (int(img.width * scale), int(img.height * scale)), Image.LANCZOS
        )

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85, optimize=True)
    return base64.b64encode(buf.getvalue()).decode("ascii"), "image/jpeg"


def _parse_json(text):
    """Models occasionally wrap JSON in fences despite instructions."""
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ExtractionError("No JSON found in the model response.")
    return json.loads(match.group(0))


def _as_int(value):
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def extract(raw_bytes, content_type="image/jpeg"):
    if not config.ANTHROPIC_API_KEY:
        raise ExtractionError(
            "No API key configured. Set ANTHROPIC_API_KEY to use scoresheet scanning."
        )

    b64, media_type = prepare_image(raw_bytes, content_type)

    payload = {
        "model": config.ANTHROPIC_MODEL,
        "max_tokens": 1024,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": b64,
                        },
                    },
                    {"type": "text", "text": PROMPT},
                ],
            }
        ],
    }

    try:
        response = requests.post(
            config.ANTHROPIC_URL,
            headers={
                "x-api-key": config.ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json=payload,
            timeout=90,
        )
    except requests.RequestException as exc:
        raise ExtractionError(f"Could not reach the API: {exc}") from exc

    if response.status_code != 200:
        detail = response.text[:300]
        raise ExtractionError(f"API returned {response.status_code}. {detail}")

    body = response.json()
    text = "".join(
        block.get("text", "") for block in body.get("content", [])
        if block.get("type") == "text"
    )
    data = _parse_json(text)

    player = data.get("player") or {}
    bot = data.get("bot") or {}

    result = {
        "player_captain": (data.get("player_captain") or "").strip() or None,
        "bot_captain": (data.get("bot_captain") or "").strip() or None,
        "board_side": data.get("board_side")
        if data.get("board_side") in ("basic", "advanced")
        else None,
        "bot_difficulty": data.get("bot_difficulty")
        if data.get("bot_difficulty") in config.DIFFICULTIES
        else None,
        "player": {k: _as_int(player.get(k)) for k in config.SCORE_KEYS},
        "bot": {k: _as_int(bot.get(k)) for k in config.BOT_SCORE_KEYS},
        "player_total_written": _as_int(data.get("player_total_written")),
        "bot_total_written": _as_int(data.get("bot_total_written")),
    }

    # Soft check: compare the sum we read against the total that was written
    # on the sheet. A mismatch means something was misread, but which cell is
    # wrong is a judgement call, so we flag rather than correct.
    warnings = []
    p_sum = sum(v for v in result["player"].values() if v is not None)
    b_sum = sum(v for v in result["bot"].values() if v is not None)

    if result["player_total_written"] is not None and p_sum != result["player_total_written"]:
        warnings.append(
            f"Your rows add up to {p_sum} but the sheet says "
            f"{result['player_total_written']}."
        )
    if result["bot_total_written"] is not None and b_sum != result["bot_total_written"]:
        warnings.append(
            f"The bot's rows add up to {b_sum} but the sheet says "
            f"{result['bot_total_written']}."
        )
    if any(v is None for v in result["player"].values()):
        warnings.append("Some of your cells could not be read. Check the blanks.")

    result["warnings"] = warnings
    return result
