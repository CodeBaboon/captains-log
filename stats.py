"""Aggregations for the stats page.

Everything works on a list of already-filtered rows rather than issuing its own
SQL. The dataset is small enough that this is cheaper than a query per panel,
and it keeps the filtering logic in one place.

"Perspective" is either "you" or "bot" and decides whose scores are read. The
bot has no Mission row and does not exist at all at Cadet, so several panels
change shape rather than simply swapping their numbers.
"""

from datetime import datetime

import config

ROW_LABELS = {key: label for key, label, _, _ in config.SCORE_ROWS}
ROW_COLOURS = {key: colour for key, _, _, colour in config.SCORE_ROWS}


def score_keys(perspective):
    """The bot cannot score Mission, so that row is dropped, not zeroed."""
    return config.SCORE_KEYS if perspective == "you" else config.BOT_SCORE_KEYS


def _prefix(perspective):
    return "p_" if perspective == "you" else "b_"


def _total(row, perspective):
    return row["p_total"] if perspective == "you" else row["b_total"]


def scored_games(rows):
    """Games with numbers on them. Burn games have none."""
    return [r for r in rows if r["ending"] == "resolution"]


def summary(rows, perspective):
    total_games = len(rows)
    played = scored_games(rows)

    totals = [t for t in (_total(r, perspective) for r in played) if t is not None]
    avg = round(sum(totals) / len(totals)) if totals else None
    best = max(totals) if totals else None

    if perspective == "you":
        wins = sum(1 for r in rows if r["result"] == "win")
    else:
        # A loss for the player is a win for the bot, including a Burn.
        wins = sum(1 for r in rows if r["result"] == "loss")

    return {
        "games": total_games,
        "wins": wins,
        "losses": total_games - wins,
        "avg_points": avg,
        "best": best,
        "burns": sum(1 for r in rows if r["ending"] == "burn"),
    }


def trend(rows, perspective):
    """Score per game over time, oldest first, for the line chart."""
    points = []
    for row in sorted(scored_games(rows), key=lambda r: (r["played_on"], r["id"])):
        value = _total(row, perspective)
        if value is None:
            continue
        points.append({
            "date": row["played_on"],
            "total": value,
            "result": row["result"],
            "id": row["id"],
        })
    return points


def category_averages(rows, perspective):
    """Average points per category, yours beside the bot's for contrast."""
    played = scored_games(rows)
    if not played:
        return []

    mine = _prefix(perspective)
    theirs = "b_" if perspective == "you" else "p_"

    out = []
    for key in score_keys(perspective):
        own = [r[mine + key] for r in played if r[mine + key] is not None]
        if not own:
            continue

        other_values = []
        if key in config.BOT_SCORE_KEYS:
            other_values = [
                r[theirs + key] for r in played if r[theirs + key] is not None
            ]

        out.append({
            "key": key,
            "label": ROW_LABELS[key],
            "colour": ROW_COLOURS[key],
            "own": round(sum(own) / len(own), 1),
            "other": round(sum(other_values) / len(other_values), 1)
                     if other_values else None,
            "n": len(own),
        })

    out.sort(key=lambda c: c["own"], reverse=True)
    return out


def composition_by_captain(rows, perspective, min_games=2):
    """What share of each captain's average total comes from each category.

    Shares are used rather than raw averages because averages do not sum:
    stacking one captain's 20 on another's 14 describes no real game. Shares do
    sum to 100, so the bar is honest and every captain gets equal width.
    """
    played = scored_games(rows)
    field = "player_captain" if perspective == "you" else "bot_captain"
    mine = _prefix(perspective)

    grouped = {}
    for row in played:
        name = row[field]
        if not name:
            continue
        grouped.setdefault(name, []).append(row)

    keys = score_keys(perspective)
    out = []
    for name, games in grouped.items():
        if len(games) < min_games:
            continue

        averages = {}
        for key in keys:
            values = [g[mine + key] for g in games if g[mine + key] is not None]
            averages[key] = sum(values) / len(values) if values else 0

        # Negative Card VP would make shares meaningless, so clamp at zero for
        # the width calculation while still reporting the true total.
        positive = {k: max(v, 0) for k, v in averages.items()}
        spread = sum(positive.values())
        if spread <= 0:
            continue

        totals = [_total(g, perspective) for g in games]
        totals = [t for t in totals if t is not None]

        out.append({
            "captain": name,
            "games": len(games),
            "average": round(sum(totals) / len(totals)) if totals else 0,
            "segments": [
                {
                    "key": key,
                    "label": ROW_LABELS[key],
                    "colour": ROW_COLOURS[key],
                    "share": round(positive[key] / spread * 100, 1),
                    "value": round(averages[key], 1),
                }
                for key in keys if positive[key] > 0
            ],
        })

    out.sort(key=lambda c: c["average"], reverse=True)
    return out


def win_rate_by_rank(rows, perspective):
    """Record at each rank, including ranks never played so gaps are visible."""
    buckets = {rank: {"wins": 0, "games": 0} for rank in config.DIFFICULTIES}

    for row in rows:
        rank = row["bot_difficulty"]
        if rank not in buckets:
            continue
        buckets[rank]["games"] += 1
        won = row["result"] == "win" if perspective == "you" else row["result"] == "loss"
        if won:
            buckets[rank]["wins"] += 1

    out = []
    for rank in config.DIFFICULTIES:
        data = buckets[rank]
        # Cadet has no bot, so it is not a rank the bot can have a record at.
        if perspective == "bot" and rank == config.SOLO_RANK:
            continue
        out.append({
            "rank": rank,
            "wins": data["wins"],
            "games": data["games"],
            "percent": round(data["wins"] / data["games"] * 100)
                       if data["games"] else None,
        })
    return out


def trend_geometry(points, width=340, height=90, pad_left=26, pad_bottom=16):
    """Turn trend points into SVG coordinates plus the reference line.

    Returns None when there is too little data to be worth drawing.
    """
    if len(points) < 2:
        return None

    values = [p["total"] for p in points]
    low = min(min(values), config.SOLO_WIN_SCORE)
    high = max(max(values), config.SOLO_WIN_SCORE)
    if high == low:
        high = low + 1

    span = high - low
    headroom = span * 0.15
    low -= headroom
    high += headroom
    span = high - low

    plot_w = width - pad_left - 8
    plot_h = height - pad_bottom - 8

    def x_at(index):
        if len(points) == 1:
            return pad_left + plot_w / 2
        return pad_left + (index / (len(points) - 1)) * plot_w

    def y_at(value):
        return 8 + (1 - (value - low) / span) * plot_h

    plotted = [
        {
            "x": round(x_at(i), 1),
            "y": round(y_at(p["total"]), 1),
            "total": p["total"],
            "result": p["result"],
            "date": p["date"],
            "id": p["id"],
        }
        for i, p in enumerate(points)
    ]

    def month(value):
        try:
            return datetime.strptime(value, "%Y-%m-%d").strftime("%b").upper()
        except ValueError:
            return ""

    return {
        "width": width,
        "height": height,
        "points": plotted,
        "polyline": " ".join(f"{p['x']},{p['y']}" for p in plotted),
        "target": round(y_at(config.SOLO_WIN_SCORE), 1),
        "target_value": config.SOLO_WIN_SCORE,
        "first_label": month(points[0]["date"]),
        "last_label": month(points[-1]["date"]),
        "pad_left": pad_left,
    }
