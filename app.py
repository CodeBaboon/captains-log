"""Captain's Log, a solo game tracker for Star Trek: Captain's Chair."""

import os
import secrets
from datetime import date, datetime
from functools import wraps

from flask import (
    Flask, abort, flash, g, jsonify, redirect, render_template, request,
    send_from_directory, session, url_for,
)
from werkzeug.security import check_password_hash

import config
import db
import extract

app = Flask(__name__)
app.config["SECRET_KEY"] = config.SECRET_KEY
app.config["MAX_CONTENT_LENGTH"] = config.MAX_UPLOAD_BYTES
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

db.init_db()


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            return redirect(url_for("login", next=request.path))
        g.user = db.get_user(session["user_id"])
        if g.user is None:
            session.clear()
            return redirect(url_for("login"))
        return view(*args, **kwargs)

    return wrapped


@app.template_filter("stardate")
def stardate(value):
    """A decorative stardate. Not canon, just pleasant.

    Format is SD YYMM.DD, which keeps it readable as an actual date.
    """
    if isinstance(value, str):
        try:
            value = datetime.strptime(value, "%Y-%m-%d").date()
        except ValueError:
            return ""
    return f"SD {value.strftime('%y%m')}.{value.strftime('%d')}"


@app.template_filter("prettydate")
def prettydate(value):
    if isinstance(value, str):
        try:
            value = datetime.strptime(value, "%Y-%m-%d").date()
        except ValueError:
            return value
    return value.strftime("%b %-d") if os.name != "nt" else value.strftime("%b %d")


# --------------------------------------------------------------------------
# Auth
# --------------------------------------------------------------------------

@app.route("/setup", methods=["GET", "POST"])
def setup():
    """First-run account creation, only reachable while no users exist."""
    if db.user_count() > 0:
        return redirect(url_for("login"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        if not username or len(password) < 8:
            flash("Pick a username and a password of at least 8 characters.")
        else:
            user_id = db.create_user(username, password)
            session["user_id"] = user_id
            return redirect(url_for("log"))

    return render_template("setup.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if db.user_count() == 0:
        return redirect(url_for("setup"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = db.get_user_by_name(username)
        if user and check_password_hash(user["password_hash"], password):
            session.clear()
            session["user_id"] = user["id"]
            session.permanent = True
            target = request.args.get("next") or url_for("log")
            return redirect(target)
        flash("That username and password did not match.")

    return render_template("login.html")


@app.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# --------------------------------------------------------------------------
# Game log
# --------------------------------------------------------------------------

@app.route("/")
@login_required
def log():
    games = db.list_games(g.user["id"], limit=config.PAGE_SIZE)
    total = db.count_games(g.user["id"])
    return render_template(
        "log.html",
        games=games,
        stats=db.stats(g.user["id"]),
        has_more=total > config.PAGE_SIZE,
        next_offset=config.PAGE_SIZE,
    )


@app.get("/log/page")
@login_required
def log_page():
    """Returns the next chunk of rows as an HTML fragment."""
    try:
        offset = max(0, int(request.args.get("offset", 0)))
    except ValueError:
        offset = 0

    games = db.list_games(g.user["id"], limit=config.PAGE_SIZE, offset=offset)
    total = db.count_games(g.user["id"])
    return jsonify(
        {
            "html": render_template("_game_rows.html", games=games),
            "has_more": total > offset + config.PAGE_SIZE,
            "next_offset": offset + config.PAGE_SIZE,
        }
    )


# --------------------------------------------------------------------------
# Game entry
# --------------------------------------------------------------------------

def _parse_game_form(form):
    """Turn posted form fields into a row dict, or raise ValueError."""
    played_on = form.get("played_on", "").strip()
    try:
        datetime.strptime(played_on, "%Y-%m-%d")
    except ValueError:
        raise ValueError("Enter a valid date.")

    player_captain = form.get("player_captain", "").strip()
    bot_captain = form.get("bot_captain", "").strip()
    if not player_captain or not bot_captain:
        raise ValueError("Both captains are required.")

    board_side = form.get("board_side")
    if board_side not in ("basic", "advanced"):
        raise ValueError("Choose Basic or Advanced.")

    difficulty = form.get("bot_difficulty")
    if difficulty not in config.DIFFICULTIES:
        raise ValueError("Choose a bot difficulty.")

    ending = form.get("ending")
    if ending not in ("resolution", "burn"):
        raise ValueError("Choose how the game ended.")

    data = {
        "played_on": played_on,
        "player_captain": player_captain,
        "board_side": board_side,
        "bot_captain": bot_captain,
        "bot_difficulty": difficulty,
        "ending": ending,
        "notes": form.get("notes", "").strip() or None,
    }

    if ending == "burn":
        # The Incident deck emptied, so the player loses outright and no
        # scores were recorded.
        for key in config.SCORE_KEYS:
            data[f"p_{key}"] = None
        for key in config.BOT_SCORE_KEYS:
            data[f"b_{key}"] = None
        data["p_total"] = None
        data["b_total"] = None
        data["result"] = "loss"
        return data

    def cell(name):
        raw = form.get(name, "").strip()
        if raw in ("", "-"):
            return 0
        try:
            return int(raw)
        except ValueError:
            raise ValueError(f"'{raw}' is not a whole number.")

    p_total = 0
    for key in config.SCORE_KEYS:
        # Mission scores nothing on the Basic side of the board.
        if key == "mission" and board_side == "basic":
            data["p_mission"] = None
            continue
        value = cell(f"p_{key}")
        data[f"p_{key}"] = value
        p_total += value

    b_total = 0
    for key in config.BOT_SCORE_KEYS:
        value = cell(f"b_{key}")
        data[f"b_{key}"] = value
        b_total += value

    data["p_total"] = p_total
    data["b_total"] = b_total
    # There are no draws against the bot. Anything short of more points is a loss.
    data["result"] = "win" if p_total > b_total else "loss"
    return data


def _save_photo(file_storage):
    if not file_storage or not file_storage.filename:
        return None
    ext = os.path.splitext(file_storage.filename)[1].lower()
    if ext not in (".jpg", ".jpeg", ".png", ".webp", ".heic"):
        ext = ".jpg"
    name = f"{datetime.now().strftime('%Y%m%d')}-{secrets.token_hex(6)}{ext}"
    config.PHOTO_DIR.mkdir(parents=True, exist_ok=True)
    file_storage.save(config.PHOTO_DIR / name)
    return name


@app.route("/games/new", methods=["GET", "POST"])
@login_required
def new_game():
    if request.method == "POST":
        try:
            data = _parse_game_form(request.form)
        except ValueError as exc:
            flash(str(exc))
            return render_template(
                "game_form.html",
                captains=db.list_captains(),
                difficulties=config.DIFFICULTIES,
                rows=config.SCORE_ROWS,
                game=request.form,
                today=date.today().isoformat(),
                mode="new",
            )

        data["user_id"] = g.user["id"]
        data["created_at"] = db.now_iso()
        data["photo_path"] = _save_photo(request.files.get("photo"))

        db.ensure_captain(data["player_captain"])
        db.ensure_captain(data["bot_captain"])
        game_id = db.insert_game(data)
        return redirect(url_for("game_detail", game_id=game_id))

    return render_template(
        "game_form.html",
        captains=db.list_captains(),
        difficulties=config.DIFFICULTIES,
        rows=config.SCORE_ROWS,
        game=None,
        today=date.today().isoformat(),
        mode="new",
    )


@app.route("/games/<int:game_id>", methods=["GET", "POST"])
@login_required
def game_detail(game_id):
    game = db.get_game(game_id, g.user["id"])
    if game is None:
        abort(404)

    if request.method == "POST":
        try:
            data = _parse_game_form(request.form)
        except ValueError as exc:
            flash(str(exc))
            return redirect(url_for("edit_game", game_id=game_id))

        data["photo_path"] = _save_photo(request.files.get("photo")) or game["photo_path"]
        db.ensure_captain(data["player_captain"])
        db.ensure_captain(data["bot_captain"])
        db.update_game(game_id, g.user["id"], data)
        return redirect(url_for("game_detail", game_id=game_id))

    return render_template("game_detail.html", game=game, rows=config.SCORE_ROWS)


@app.get("/games/<int:game_id>/edit")
@login_required
def edit_game(game_id):
    game = db.get_game(game_id, g.user["id"])
    if game is None:
        abort(404)
    return render_template(
        "game_form.html",
        captains=db.list_captains(),
        difficulties=config.DIFFICULTIES,
        rows=config.SCORE_ROWS,
        game=game,
        today=date.today().isoformat(),
        mode="edit",
    )


@app.post("/games/<int:game_id>/delete")
@login_required
def remove_game(game_id):
    photo = db.delete_game(game_id, g.user["id"])
    if photo:
        try:
            (config.PHOTO_DIR / photo).unlink(missing_ok=True)
        except OSError:
            pass
    return redirect(url_for("log"))


@app.get("/photos/<path:name>")
@login_required
def photo(name):
    return send_from_directory(config.PHOTO_DIR, name)


# --------------------------------------------------------------------------
# Scoresheet scanning
# --------------------------------------------------------------------------

@app.post("/api/extract")
@login_required
def api_extract():
    upload = request.files.get("photo")
    if not upload or not upload.filename:
        return jsonify({"error": "No photo was uploaded."}), 400

    raw = upload.read()
    if not raw:
        return jsonify({"error": "That file was empty."}), 400

    try:
        result = extract.extract(raw, upload.mimetype or "image/jpeg")
    except extract.ExtractionError as exc:
        return jsonify({"error": str(exc)}), 502

    return jsonify(result)


@app.errorhandler(413)
def too_large(_):
    return "That photo is too large. Try a smaller one.", 413


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)), debug=True)
