"""Exercise the stats page filters and aggregations."""

import os
import shutil
import tempfile

TMP = tempfile.mkdtemp()
os.environ["CC_DATA_DIR"] = TMP
os.environ["CC_SECRET_KEY"] = "test-key"

import config  # noqa: E402
import app as application  # noqa: E402
import db  # noqa: E402
import stats as analytics  # noqa: E402

app = application.app
app.config["TESTING"] = True
client = app.test_client()
client.post("/setup", data={"username": "dave", "password": "longenough1"})

failures = []


def check(label, condition, detail=""):
    if condition:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label} {detail}")
        failures.append(label)


def game(**kw):
    base = {
        "played_on": "2026-08-01", "player_captain": "Georgiou",
        "board_side": "advanced", "bot_captain": "Soval",
        "bot_difficulty": "Lieutenant", "ending": "resolution",
        "p_glory": "10", "b_glory": "5", "p_locations": "4", "b_locations": "3",
        "p_endgame": "8", "b_endgame": "6", "p_card_vp": "20", "b_card_vp": "10",
        "p_research": "6", "b_research": "4", "p_influence": "4", "b_influence": "2",
        "p_military": "2", "b_military": "1", "p_mission": "6",
    }
    base.update({k: str(v) for k, v in kw.items()})
    client.post("/games/new", data=base)


print("\nfixtures")
game(played_on="2026-06-01", p_card_vp=20)
game(played_on="2026-06-15", player_captain="Kirk", p_glory=30, p_card_vp=4)
game(played_on="2026-07-01", bot_captain="Khan", bot_difficulty="Commander",
     p_card_vp=2, b_card_vp=40)
game(played_on="2026-07-10", board_side="basic", p_mission=99)
game(played_on="2026-07-20", player_captain="Kirk", p_glory=28, p_card_vp=6)
game(played_on="2026-08-01", bot_difficulty="Cadet", bot_captain="",
     p_card_vp=40)
game(played_on="2026-08-05", ending="burn")
print(f"  {db.count_games(1)} games created")

print("\npage loads")
r = client.get("/stats")
check("stats page renders", r.status_code == 200 and b"Score over time" in r.data)
check("log links to stats", b"/stats" in client.get("/").data)

print("\nfilters")
r = client.get("/stats?board=basic")
check("board filter narrows", b"1 of 7 games" in r.data,
      r.data.decode().split("games")[0][-40:])

r = client.get("/stats?captain=Kirk")
check("captain filter narrows", b"2 of 7 games" in r.data)

r = client.get("/stats?captain=Kirk&captain=Georgiou")
check("multi-select unions", b"7 of 7 games" in r.data)

r = client.get("/stats?rank=Commander&rank=Cadet")
check("rank multi-select works", b"2 of 7 games" in r.data)

r = client.get("/stats")
check("no filter means all", b"7 of 7 games" in r.data)

r = client.get("/stats?captain=NotAReal.Captain")
check("unknown filter value ignored", b"7 of 7 games" in r.data)

r = client.get("/stats?board=advanced&board=basic")
check("selecting every option equals none selected", b"7 of 7 games" in r.data)

print("\nperspective")
r = client.get("/stats?side=bot")
check("bot view drops cadet games", b"6 of 6 games" in r.data,
      r.data.decode().split("games")[0][-40:])
check("bot view relabels win rate", b"The bot&#39;s win rate" in r.data
      or b"The bot's win rate" in r.data)

rows = db.filtered_games(1, perspective="bot")
check("bot rows exclude solo", all(r["bot_captain"] for r in rows))

cats = analytics.category_averages(db.filtered_games(1), "bot")
check("bot has no mission category",
      "mission" not in [c["key"] for c in cats])

cats_you = analytics.category_averages(db.filtered_games(1), "you")
check("your view has mission", "mission" in [c["key"] for c in cats_you])

ranks_bot = analytics.win_rate_by_rank(db.filtered_games(1, perspective="bot"), "bot")
check("cadet absent from bot ranks",
      config.SOLO_RANK not in [x["rank"] for x in ranks_bot])

print("\naggregations")
rows = db.filtered_games(1)
s = analytics.summary(rows, "you")
check("summary counts every game", s["games"] == 7, f"got {s['games']}")
check("summary counts the burn", s["burns"] == 1)
check("wins and losses sum to games", s["wins"] + s["losses"] == s["games"])

points = analytics.trend(rows, "you")
check("burn excluded from the trend", len(points) == 6, f"got {len(points)}")
check("trend runs oldest first", points[0]["date"] < points[-1]["date"])

geo = analytics.trend_geometry(points)
check("geometry produced", geo is not None)
check("every point plotted", len(geo["points"]) == len(points))
check("target line inside the canvas", 0 <= geo["target"] <= geo["height"])
check("points inside the canvas",
      all(0 <= p["y"] <= geo["height"] for p in geo["points"]))

check("one point draws no line", analytics.trend_geometry(points[:1]) is None)
check("no points draws no line", analytics.trend_geometry([]) is None)

flat = [dict(p, total=50) for p in points]
check("identical scores do not divide by zero",
      analytics.trend_geometry(flat) is not None)

cats = analytics.category_averages(rows, "you")
check("categories sorted by size",
      all(cats[i]["own"] >= cats[i + 1]["own"] for i in range(len(cats) - 1)))
check("categories carry a sample size", all(c["n"] > 0 for c in cats))

comps = analytics.composition_by_captain(rows, "you")
check("composition groups by captain", len(comps) == 2, f"got {len(comps)}")
for entry in comps:
    total = sum(s["share"] for s in entry["segments"])
    check(f"{entry['captain']} shares sum to 100", abs(total - 100) < 0.5,
          f"got {total}")

singleton = analytics.composition_by_captain(rows, "you", min_games=99)
check("min_games still filters when asked", singleton == [])

solo_rows = db.filtered_games(1, captains=["Kirk"])
one_game = analytics.composition_by_captain(solo_rows[:1], "you")
check("a single game still appears", len(one_game) == 1, f"got {len(one_game)}")
check("single game reports its count", one_game and one_game[0]["games"] == 1)

print("\npresentation")
r = client.get("/stats")
check("panel renamed", b"Point breakdown" in r.data)
check("n-notation gone from the page", b">n0<" not in r.data and b" n2<" not in r.data)
check("win rate shows a record", b"No games" in r.data)
check("win rate has no value column", b'mrow-wide' in r.data)
check("subtitles removed", b"two games minimum" not in r.data
      and b"Sample size shown" not in r.data)
check("captain picker starts closed", b"<details class=\"picker\">" in r.data)

r = client.get("/stats?captain=Kirk")
check("picker stays closed after applying",
      b"<details class=\"picker\" open>" not in r.data)

r = client.get("/")
check("log buttons share a row", b"actions-row" in r.data)

pts = analytics.trend(db.filtered_games(1), "you")
same = [dict(p, date="2026-08-0%d" % (i + 1)) for i, p in enumerate(pts[:4])]
geo = analytics.trend_geometry(same)
check("single month labels carry the day", geo["first_label"] != geo["last_label"],
      f"{geo['first_label']} / {geo['last_label']}")

spread = [dict(pts[0], date="2026-06-01"), dict(pts[1], date="2026-08-01")]
geo = analytics.trend_geometry(spread)
check("multi month labels are months", geo["first_label"] == "JUN"
      and geo["last_label"] == "AUG", f"{geo['first_label']} / {geo['last_label']}")

print("\nedge cases")
game(played_on="2026-08-10", player_captain="Khan", p_card_vp=-30, p_glory=1,
     p_locations=0, p_endgame=0, p_research=0, p_influence=0, p_military=0,
     p_mission=0)
game(played_on="2026-08-11", player_captain="Khan", p_card_vp=-30, p_glory=1,
     p_locations=0, p_endgame=0, p_research=0, p_influence=0, p_military=0,
     p_mission=0)
rows = db.filtered_games(1)
comps = analytics.composition_by_captain(rows, "you")
khan = [c for c in comps if c["captain"] == "Khan"]
check("negative totals do not break shares",
      not khan or abs(sum(s["share"] for s in khan[0]["segments"]) - 100) < 0.5)
check("negative average still reported",
      not khan or khan[0]["average"] < 0, f"got {khan[0]['average'] if khan else 'n/a'}")

r = client.get("/stats?captain=Rebner")
check("empty result shows a message", b"Nothing matches" in r.data)

r = client.get("/stats?side=nonsense")
check("bad perspective falls back", r.status_code == 200)

other = app.test_client()
check("stats needs a login", b"Sign in" in other.get("/stats", follow_redirects=True).data)

shutil.rmtree(TMP, ignore_errors=True)
print()
if failures:
    print(f"{len(failures)} check(s) failed: {', '.join(failures)}")
    raise SystemExit(1)
print("all checks passed")
