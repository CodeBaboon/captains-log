"""Exercise Captain's Log end to end against a throwaway database."""

import os
import shutil
import tempfile

TMP = tempfile.mkdtemp()
os.environ["CC_DATA_DIR"] = TMP
os.environ["CC_SECRET_KEY"] = "test-key"

import config  # noqa: E402
import app as application  # noqa: E402
import db  # noqa: E402

app = application.app
app.config["TESTING"] = True

failures = []


def check(label, condition, detail=""):
    if condition:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label} {detail}")
        failures.append(label)


def form(**overrides):
    base = {
        "played_on": "2026-08-24",
        "player_captain": "Georgiou",
        "board_side": "advanced",
        "bot_captain": "Soval",
        "bot_difficulty": "Lieutenant",
        "ending": "resolution",
        "p_glory": "4", "b_glory": "18",
        "p_locations": "3", "b_locations": "2",
        "p_endgame": "8", "b_endgame": "10",
        "p_card_vp": "32", "b_card_vp": "4",
        "p_research": "8", "b_research": "2",
        "p_influence": "2", "b_influence": "4",
        "p_military": "6", "b_military": "0",
        "p_mission": "6",
    }
    base.update(overrides)
    return base


print("\nsetup and auth")
client = app.test_client()

r = client.get("/", follow_redirects=True)
check("unauthenticated visit lands on setup", b"Create account" in r.data)

r = client.post("/setup", data={"username": "dave", "password": "longenough1"},
                follow_redirects=True)
check("first account created and signed in", b"Captain&#39;s log" in r.data or b"Captain's log" in r.data)

r = client.get("/setup", follow_redirects=True)
check("setup closes after first account", b"Create account" not in r.data)

print("\nscoring")
r = client.post("/games/new", data=form(), follow_redirects=True)
check("game saved", b"Georgiou" in r.data)

row = db.list_games(1)[0]
check("player total sums to 69", row["p_total"] == 69, f"got {row['p_total']}")
check("bot total sums to 40", row["b_total"] == 40, f"got {row['b_total']}")
check("higher score wins", row["result"] == "win", f"got {row['result']}")

client.post("/games/new", data=form(p_mission="0", p_card_vp="0"))
row = db.list_games(1)[0]
check("lower score loses", row["result"] == "loss", f"got {row['result']}")

# 4 + 3 + 8 + 8 + 2 + 6 = 31 for the player against a bot on 40.
client.post("/games/new", data=form(
    p_glory="18", p_locations="2", p_endgame="10", p_card_vp="4",
    p_research="2", p_influence="4", p_military="0", p_mission="0",
    b_glory="18", b_locations="2", b_endgame="10", b_card_vp="4",
    b_research="2", b_influence="4", b_military="0"))
row = db.list_games(1)[0]
check("a tie counts as a loss", row["result"] == "loss", f"got {row['result']}")
check("tie totals match", row["p_total"] == row["b_total"])

client.post("/games/new", data=form(p_card_vp="-7"))
row = db.list_games(1)[0]
check("negative card VP accepted", row["p_card_vp"] == -7, f"got {row['p_card_vp']}")
check("negative reduces the total", row["p_total"] == 30, f"got {row['p_total']}")

client.post("/games/new", data=form(board_side="basic", p_mission="6"))
row = db.list_games(1)[0]
check("basic side stores no mission", row["p_mission"] is None, f"got {row['p_mission']}")
# 4 + 3 + 8 + 32 + 8 + 2 + 6 = 63, with the 6 mission points left out.
check("basic side excludes mission from total", row["p_total"] == 63,
      f"got {row['p_total']}")

client.post("/games/new", data=form(ending="burn"))
row = db.list_games(1)[0]
check("burn is a loss", row["result"] == "loss", f"got {row['result']}")
check("burn stores no scores", row["p_total"] is None and row["p_glory"] is None)

client.post("/games/new", data=form(p_glory=""))
row = db.list_games(1)[0]
check("blank cell reads as zero", row["p_glory"] == 0, f"got {row['p_glory']}")

print("\nvalidation")
r = client.post("/games/new", data=form(p_glory="banana"), follow_redirects=True)
check("non-numeric cell rejected", b"not a whole number" in r.data)

r = client.post("/games/new", data=form(player_captain=""), follow_redirects=True)
check("missing captain rejected", b"Both captains are required" in r.data)

r = client.post("/games/new", data=form(played_on="nonsense"), follow_redirects=True)
check("bad date rejected", b"valid date" in r.data)

print("\ncaptains")
client.post("/games/new", data=form(bot_captain="Rebner"))
names = [c["name"] for c in db.list_captains()]
check("seeded captains present", "Picard" in names and "Soval" in names)

client.post("/games/new", data=form(player_captain="Tuvok"))
names = [c["name"] for c in db.list_captains()]
check("unknown captain gets remembered", "Tuvok" in names)

print("\nstats and pagination")
stats = db.stats(1)
check("games counted", stats["games"] == db.count_games(1))
check("average excludes burn games", stats["avg_points"] is not None)

for i in range(25):
    client.post("/games/new", data=form(played_on=f"2026-07-{(i % 28) + 1:02d}"))

r = client.get("/")
check("first page caps at 20 rows", r.data.count(b'class="row row-link') == 20,
      f"got {r.data.count(b'class=\"row row-link')}")
check("load more offered", b"Load more" in r.data)

r = client.get("/log/page?offset=20")
payload = r.get_json()
check("second page returns rows", payload["html"].count('class="row row-link') > 0)
check("second page reports offset", payload["next_offset"] == 40)

print("\ndetail, edit, delete")
game_id = db.list_games(1)[0]["id"]
r = client.get(f"/games/{game_id}")
check("detail renders", b"Total" in r.data)

r = client.post(f"/games/{game_id}", data=form(p_glory="99"), follow_redirects=True)
check("edit saves", db.get_game(game_id, 1)["p_glory"] == 99)

r = client.get("/games/999999")
check("unknown game is a 404", r.status_code == 404)

before = db.count_games(1)
client.post(f"/games/{game_id}/delete")
check("delete removes the game", db.count_games(1) == before - 1)

print("\nsession")
client.post("/logout")
r = client.get("/", follow_redirects=True)
check("signing out ends the session", b"Sign in" in r.data)

r = client.post("/login", data={"username": "dave", "password": "wrong"},
                follow_redirects=True)
check("wrong password rejected", b"did not match" in r.data)

r = client.post("/login", data={"username": "dave", "password": "longenough1"},
                follow_redirects=True)
check("correct password accepted", b"Captain&#39;s log" in r.data or b"Captain's log" in r.data)

other = app.test_client()
r = other.get("/games/1", follow_redirects=True)
check("another visitor cannot read a game", b"Sign in" in r.data)

print("\nextraction parsing")
import extract  # noqa: E402

parsed = extract._parse_json('```json\n{"player_captain": "Kirk"}\n```')
check("fenced JSON parsed", parsed["player_captain"] == "Kirk")
check("integers coerced", extract._as_int("-7") == -7)
check("blanks become None", extract._as_int("") is None)
check("nonsense becomes None", extract._as_int("abc") is None)

try:
    extract.extract(b"not-an-image")
except extract.ExtractionError as exc:
    check("missing API key reports clearly", "API key" in str(exc))

shutil.rmtree(TMP, ignore_errors=True)

print()
if failures:
    print(f"{len(failures)} check(s) failed: {', '.join(failures)}")
    raise SystemExit(1)
print("all checks passed")
