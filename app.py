"""Captain's Log, a solo game tracker for Star Trek: Captain's Chair."""

import json
import os
import secrets
from datetime import date, datetime
from functools import wraps

from urllib.parse import urlparse

from flask import (
    Flask, Response, abort, flash, g, jsonify, redirect, render_template,
    request, session, url_for,
)
from werkzeug.security import check_password_hash

import access
import config
import db
import extract
import stats as analytics

app = Flask(__name__)
app.config["SECRET_KEY"] = config.SECRET_KEY
app.config["MAX_CONTENT_LENGTH"] = config.MAX_UPLOAD_BYTES
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = config.SECURE_COOKIES

db.init_db()


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        user = _current_user()
        if user is None:
            session.clear()
            return redirect(url_for("login", next=request.path))
        g.user = user
        if not g.user["is_admin"]:
            abort(403)
        return view(*args, **kwargs)

    return wrapped


def _access_user():
    """Sign in whoever Cloudflare Access has verified, creating them if new.

    Returns the user row, or None when Access is off or the request carries no
    token. A token that is present but invalid raises, because silently falling
    back to the password form would hide a broken configuration.
    """
    if not access.enabled() or not access.token_from(request):
        return None

    email = access.identify(request)
    user = db.get_user_by_email(email)
    if user is None:
        db.create_access_user(email, access.username_for(email))
        user = db.get_user_by_email(email)

    session["user_id"] = user["id"]
    session.permanent = True
    return user


def _current_user():
    """The signed-in user: Access first, then an existing session."""
    try:
        user = _access_user()
    except access.AccessError:
        # A bad token is a configuration problem, not a visitor problem.
        app.logger.warning("Rejected an Access token", exc_info=True)
        session.clear()
        abort(403)

    if user is not None:
        return user

    if session.get("user_id"):
        return db.get_user(session["user_id"])
    return None


def safe_next(target):
    """Only allow redirects to a path on this site.

    `next` arrives from the query string, so without this a crafted link to our
    own login page could bounce someone to another site after they sign in.
    """
    if not target:
        return None
    parsed = urlparse(target)
    if parsed.scheme or parsed.netloc:
        return None
    if not target.startswith("/") or target.startswith("//"):
        return None
    return target


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        user = _current_user()
        if user is None:
            session.clear()
            return redirect(url_for("login", next=request.path))
        g.user = user
        return view(*args, **kwargs)

    return wrapped


@app.context_processor
def inject_user():
    user = getattr(g, "user", None)
    if user is None and session.get("user_id"):
        user = db.get_user(session["user_id"])
    return {"current_user": user}


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
    # Behind Access, arriving at /login with a valid token signs you straight in.
    if access.enabled() and access.token_from(request):
        try:
            if _access_user():
                return redirect(safe_next(request.args.get("next")) or url_for("log"))
        except access.AccessError:
            abort(403)

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
            return redirect(safe_next(request.args.get("next")) or url_for("log"))
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
# Settings and accounts
# --------------------------------------------------------------------------

@app.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    if request.method == "POST":
        try:
            db.rename_user(g.user["id"], request.form.get("username"))
            flash("Name updated.")
        except ValueError as exc:
            flash(str(exc))
        return redirect(url_for("settings"))

    return render_template(
        "settings.html",
        account=db.get_user(g.user["id"]),
        game_count=db.count_games(g.user["id"]),
        access_on=access.enabled(),
    )


@app.get("/users")
@admin_required
def users_page():
    return render_template("users.html", users=db.list_users(),
                           access_on=access.enabled())


@app.post("/users/<int:user_id>")
@admin_required
def users_update(user_id):
    action = request.form.get("action")

    try:
        if action == "email":
            db.set_user_email(user_id, request.form.get("email"))
        elif action == "rename":
            db.rename_user(user_id, request.form.get("username"))
        elif action == "promote":
            db.set_user_admin(user_id, True)
        elif action == "demote":
            db.set_user_admin(user_id, False)
        elif action == "delete":
            db.delete_user(user_id)
        else:
            flash("Unknown action.")
    except ValueError as exc:
        flash(str(exc))

    return redirect(url_for("users_page"))


# --------------------------------------------------------------------------
# Captain list
# --------------------------------------------------------------------------

@app.get("/captains")
@admin_required
def captains_page():
    usage = db.captain_usage()
    captains = db.list_captains()
    for captain in captains:
        captain["games"] = usage.get(captain["name"], 0)
    boxes = db.list_boxes()
    in_box = db.box_usage()
    for box in boxes:
        box["captains"] = in_box.get(box["name"], 0)

    return render_template(
        "captains.html",
        captains=captains,
        boxes=boxes,
        total=sum(usage.values()),
    )


@app.post("/captains")
@admin_required
def captains_add():
    name = (request.form.get("name") or "").strip()
    box = request.form.get("box") or ""

    existing = db.captain_exists(name)
    if not name:
        flash("Enter a name.")
    elif len(name) > 60:
        flash("That name is too long.")
    elif existing:
        flash(f"{existing} is already on the list.")
    else:
        try:
            db.add_captain(name, box)
        except ValueError as exc:
            flash(str(exc))

    return redirect(url_for("captains_page"))


@app.post("/captains/groups")
@admin_required
def boxes_add():
    try:
        db.add_box(request.form.get("name"))
    except ValueError as exc:
        flash(str(exc))
    return redirect(url_for("captains_page"))


@app.post("/captains/groups/<int:box_id>/delete")
@admin_required
def boxes_delete(box_id):
    try:
        db.delete_box(box_id)
    except ValueError as exc:
        flash(str(exc))
    return redirect(url_for("captains_page"))


@app.post("/captains/<int:captain_id>")
@admin_required
def captains_update(captain_id):
    action = request.form.get("action")

    try:
        if action == "rename":
            db.rename_captain(captain_id, request.form.get("name"),
                              request.form.get("box"))
        elif action == "delete":
            db.delete_captain(captain_id)
        else:
            flash("Unknown action.")
    except ValueError as exc:
        flash(str(exc))

    return redirect(url_for("captains_page"))


# --------------------------------------------------------------------------
# Stats
# --------------------------------------------------------------------------

def _selected(name, allowed):
    """Read a repeated query parameter, keeping only recognised values."""
    chosen = [v for v in request.args.getlist(name) if v in allowed]
    # An empty selection means no filter, so every group falls back to all.
    return chosen


@app.get("/stats")
@login_required
def stats_page():
    perspective = request.args.get("side")
    if perspective not in ("you", "bot"):
        perspective = "you"

    captain_field = "player_captain" if perspective == "you" else "bot_captain"
    counts = db.captain_counts(g.user["id"], captain_field)
    known = [c["name"] for c in db.list_captains()]
    # Include any captain that appears in the log even if delisted since.
    for name in counts:
        if name not in known:
            known.append(name)

    chosen_captains = _selected("captain", set(known))
    chosen_boards = _selected("board", {"basic", "advanced"})
    chosen_ranks = _selected("rank", set(config.DIFFICULTIES))

    rows = db.filtered_games(
        g.user["id"],
        perspective=perspective,
        captains=chosen_captains,
        boards=chosen_boards,
        ranks=chosen_ranks,
    )
    everything = db.filtered_games(g.user["id"], perspective=perspective)

    points = analytics.trend(rows, perspective)

    return render_template(
        "stats.html",
        perspective=perspective,
        summary=analytics.summary(rows, perspective),
        geometry=analytics.trend_geometry(points),
        point_count=len(points),
        records=analytics.record_by_captain(rows, perspective),
        categories=analytics.category_averages(rows, perspective),
        compositions=analytics.composition_by_captain(rows, perspective),
        ranks=analytics.win_rate_by_rank(rows, perspective),
        captains=db.list_captains(),
        captain_counts=counts,
        extra_captains=[n for n in known if n not in [c["name"] for c in db.list_captains()]],
        boxes=db.box_names(),
        difficulties=config.DIFFICULTIES,
        chosen_captains=chosen_captains,
        chosen_boards=chosen_boards,
        chosen_ranks=chosen_ranks,
        shown=len(rows),
        available=len(everything),
        solo_rank=config.SOLO_RANK,
        config_rows=config.SCORE_ROWS,
    )


@app.get("/captain/<name>")
@login_required
def captain_page(name):
    perspective = request.args.get("side")
    if perspective not in ("you", "bot"):
        perspective = "you"

    canonical = db.captain_exists(name)
    field = "player_captain" if perspective == "you" else "bot_captain"
    counts = db.captain_counts(g.user["id"], field)

    # Fall back to the name as logged, so a captain removed from the list can
    # still be looked at.
    if not canonical:
        canonical = next((n for n in counts if n.lower() == name.lower()), None)
    if not canonical:
        abort(404)

    rows = db.filtered_games(g.user["id"], perspective=perspective,
                             captains=[canonical])
    if not rows:
        abort(404)

    everything = db.filtered_games(g.user["id"], perspective=perspective)
    box = next((c["box"] for c in db.list_captains() if c["name"] == canonical), None)

    return render_template(
        "captain.html",
        name=canonical,
        box=box,
        perspective=perspective,
        summary=analytics.summary(rows, perspective),
        opponents=analytics.record_vs_opponents(rows, perspective),
        deltas=analytics.baseline_delta(rows, everything, perspective),
        ladder=analytics.rank_ladder(rows, perspective),
        games=rows[:8],
        total_games=len(rows),
    )


# --------------------------------------------------------------------------
# Game entry
# --------------------------------------------------------------------------

def _resolve_captain(form, field, label):
    """Take a captain from the dropdown.

    Captains are managed on their own page, so logging a game can only pick
    from the list. That stops a typo from quietly minting a new captain.
    """
    choice = (form.get(field) or "").strip()
    if not choice:
        raise ValueError(f"Choose {label}.")

    known = db.captain_exists(choice)
    if not known:
        raise ValueError(f"{choice} is not on the captain list.")
    return known


def _parse_game_form(form):
    """Turn posted form fields into a row dict, or raise ValueError."""
    played_on = form.get("played_on", "").strip()
    try:
        datetime.strptime(played_on, "%Y-%m-%d")
    except ValueError:
        raise ValueError("Enter a valid date.")

    player_captain = _resolve_captain(form, "player_captain", "your captain")

    board_side = form.get("board_side")
    if board_side not in ("basic", "advanced"):
        raise ValueError("Choose Basic or Advanced.")

    difficulty = form.get("bot_difficulty")
    if not difficulty:
        raise ValueError("Choose a rank.")
    if difficulty not in config.DIFFICULTIES:
        raise ValueError("That is not a rank.")

    solo = difficulty == config.SOLO_RANK

    ending = form.get("ending")
    if ending not in ("resolution", "burn"):
        raise ValueError("Choose how the game ended.")

    # NOT NULL on the column, so a solo game stores an empty string rather than
    # null. Templates treat the empty string as "no opponent".
    bot_captain = "" if solo else _resolve_captain(
        form, "bot_captain", "the bot's captain")

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

    data["p_total"] = p_total

    if solo:
        # No opponent, so the target score decides it. Hitting it exactly wins.
        for key in config.BOT_SCORE_KEYS:
            data[f"b_{key}"] = None
        data["b_total"] = None
        data["result"] = "win" if p_total >= config.SOLO_WIN_SCORE else "loss"
        return data

    b_total = 0
    for key in config.BOT_SCORE_KEYS:
        value = cell(f"b_{key}")
        data[f"b_{key}"] = value
        b_total += value

    data["b_total"] = b_total
    # There are no draws against the bot. Anything short of more points is a loss.
    data["result"] = "win" if p_total > b_total else "loss"
    return data


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
                boxes=db.box_names(),
                difficulties=config.DIFFICULTIES,
                solo_win_score=config.SOLO_WIN_SCORE,
                rows=config.SCORE_ROWS,
                game=request.form,
                today=date.today().isoformat(),
                mode="new",
            )

        data["user_id"] = g.user["id"]
        data["created_at"] = db.now_iso()

        game_id = db.insert_game(data)
        return redirect(url_for("game_detail", game_id=game_id))

    return render_template(
        "game_form.html",
        captains=db.list_captains(),
        boxes=db.box_names(),
        difficulties=config.DIFFICULTIES,
        solo_win_score=config.SOLO_WIN_SCORE,
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
        boxes=db.box_names(),
        difficulties=config.DIFFICULTIES,
        solo_win_score=config.SOLO_WIN_SCORE,
        rows=config.SCORE_ROWS,
        game=game,
        today=date.today().isoformat(),
        mode="edit",
    )


@app.post("/games/<int:game_id>/delete")
@login_required
def remove_game(game_id):
    db.delete_game(game_id, g.user["id"])
    return redirect(url_for("log"))


# --------------------------------------------------------------------------
# Export
# --------------------------------------------------------------------------

@app.get("/export.json")
@login_required
def export_games():
    """Everything this account has logged, as a file they can keep.

    Their data lives on one Raspberry Pi with no account recovery, so being
    able to walk away with it is the least the app owes them.
    """
    games = db.export_games(g.user["id"])

    for game in games:
        # Internal identifiers mean nothing outside this database.
        game.pop("user_id", None)
        game.pop("photo_path", None)

    payload = {
        "application": "Captain's Log",
        "exported_at": db.now_iso(),
        "username": g.user["username"],
        "game_count": len(games),
        "solo_win_score": config.SOLO_WIN_SCORE,
        "score_rows": [
            {"key": key, "label": label, "bot_scores": bot}
            for key, label, bot, _ in config.SCORE_ROWS
        ],
        "games": games,
    }

    body = json.dumps(payload, indent=2, ensure_ascii=False)
    stamp = datetime.now().strftime("%Y%m%d")
    return Response(
        body,
        mimetype="application/json",
        headers={
            "Content-Disposition":
                f'attachment; filename="captains-log-{stamp}.json"',
        },
    )


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
    # Local development only. In production gunicorn serves the app and binds
    # to 127.0.0.1, with the tunnel in front.
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", 8080)))
