"""The shared captain list and its admin page."""

import os
import shutil
import sqlite3
import tempfile

TMP = tempfile.mkdtemp()
os.environ["CC_DATA_DIR"] = TMP
os.environ["CC_SECRET_KEY"] = "test-key"

import app as application  # noqa: E402
import db  # noqa: E402

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
        "played_on": "2026-11-01", "player_captain": "Georgiou",
        "board_side": "advanced", "bot_captain": "Soval",
        "bot_difficulty": "Lieutenant", "ending": "resolution",
        "p_glory": "10", "b_glory": "5", "p_locations": "4", "b_locations": "3",
        "p_endgame": "8", "b_endgame": "6", "p_card_vp": "20", "b_card_vp": "10",
        "p_research": "6", "b_research": "4", "p_influence": "4", "b_influence": "2",
        "p_military": "2", "b_military": "1", "p_mission": "6",
    }
    base.update({k: str(v) for k, v in kw.items()})
    return client.post("/games/new", data=base, follow_redirects=True)


def by_name(name):
    return next((c for c in db.list_captains(include_retired=True)
                 if c["name"] == name), None)


print("\nadmin access")
r = client.get("/captains")
check("page renders for the owner", r.status_code == 200 and b"Add a captain" in r.data)
check("log links to it", b"/captains" in client.get("/").data)

check("first account is an admin", bool(db.get_user(1)["is_admin"]))

second = db.create_user("friend", "longenough2")
check("later accounts are not admins", not db.get_user(second)["is_admin"])

other = app.test_client()
other.post("/login", data={"username": "friend", "password": "longenough2"})
check("non-admin gets a 403", other.get("/captains").status_code == 403)
check("non-admin cannot add", other.post("/captains", data={"name": "Q"}).status_code == 403)
check("non-admin link hidden", b"Manage captains" not in other.get("/").data)

anon = app.test_client()
check("signed out is redirected",
      b"Sign in" in anon.get("/captains", follow_redirects=True).data)

print("\nadding")
client.post("/captains", data={"name": "Janeway", "box": "Expansion"})
check("captain added", by_name("Janeway") is not None)
check("box respected", by_name("Janeway")["box"] == "Expansion")

r = client.post("/captains", data={"name": "janeway"}, follow_redirects=True)
check("duplicate rejected case-insensitively", b"already on the list" in r.data)
check("no second row created",
      len([c for c in db.list_captains(include_retired=True)
           if c["name"].lower() == "janeway"]) == 1)

r = client.post("/captains", data={"name": "   "}, follow_redirects=True)
check("blank name rejected", b"Enter a name" in r.data)

r = client.post("/captains", data={"name": "x" * 61}, follow_redirects=True)
check("overlong name rejected", b"too long" in r.data)

r = client.post("/captains", data={"name": "Tuvok", "box": "Nonsense"},
                follow_redirects=True)
check("unknown box falls back", by_name("Tuvok")["box"] == "Other")

print("\nrenaming cascades")
game()
game(player_captain="Kirk", bot_captain="Georgiou")
georgiou = by_name("Georgiou")
usage_before = db.captain_usage()["Georgiou"]
check("usage counts both columns", usage_before == 2, f"got {usage_before}")

client.post(f"/captains/{georgiou['id']}",
            data={"action": "rename", "name": "Philippa Georgiou", "box": "To Boldly Go"})
check("captain renamed", by_name("Philippa Georgiou") is not None)
check("old name gone", by_name("Georgiou") is None)

rows = db.list_games(1)
check("player column followed the rename",
      any(r["player_captain"] == "Philippa Georgiou" for r in rows))
check("bot column followed the rename",
      any(r["bot_captain"] == "Philippa Georgiou" for r in rows))
check("no game left on the old name",
      not any(r["player_captain"] == "Georgiou" or r["bot_captain"] == "Georgiou"
              for r in rows))
check("usage carried over", db.captain_usage().get("Philippa Georgiou") == 2)

r = client.post(f"/captains/{by_name('Kirk')['id']}",
                data={"action": "rename", "name": "Janeway"}, follow_redirects=True)
check("rename onto an existing name rejected", b"already on the list" in r.data)
check("the clash left Kirk alone", by_name("Kirk") is not None)

r = client.post(f"/captains/{by_name('Kirk')['id']}",
                data={"action": "rename", "name": ""}, follow_redirects=True)
check("rename to blank rejected", b"needs a name" in r.data)

# Changing only the box must not disturb the games.
kirk = by_name("Kirk")
client.post(f"/captains/{kirk['id']}",
            data={"action": "rename", "name": "Kirk", "box": "Expansion"})
check("box changed", by_name("Kirk")["box"] == "Expansion")
check("games untouched by a box change",
      db.captain_usage().get("Kirk") == 1, str(db.captain_usage()))

print("\nretiring")
soval = by_name("Soval")
client.post(f"/captains/{soval['id']}", data={"action": "retire"})
check("retired flag set", by_name("Soval")["active"] == 0)
check("hidden from the pick list",
      "Soval" not in [c["name"] for c in db.list_captains()])
check("still visible to the admin page",
      "Soval" in [c["name"] for c in db.list_captains(include_retired=True)])
check("history intact", db.captain_usage().get("Soval") == 1)

check("retired captain still validates", db.captain_exists("Soval") == "Soval")

# A game logged before the retirement has to stay editable.
target = next(r for r in db.list_games(1) if r["bot_captain"] == "Soval")
form_page = client.get(f"/games/{target['id']}/edit")
check("edit page still offers the retired captain",
      b'value="Soval"' in form_page.data)

r = client.post(f"/games/{target['id']}", data={
    "played_on": target["played_on"], "player_captain": target["player_captain"],
    "board_side": "advanced", "bot_captain": "Soval",
    "bot_difficulty": "Lieutenant", "ending": "resolution",
    "p_glory": "11", "b_glory": "5", "p_locations": "4", "b_locations": "3",
    "p_endgame": "8", "b_endgame": "6", "p_card_vp": "20", "b_card_vp": "10",
    "p_research": "6", "b_research": "4", "p_influence": "4", "b_influence": "2",
    "p_military": "2", "b_military": "1", "p_mission": "6",
}, follow_redirects=True)
check("editing an old game with a retired captain still saves",
      db.get_game(target["id"], 1)["p_glory"] == 11)

r = client.get("/games/new")
check("new game does not offer the retired captain",
      b'value="Soval"' not in r.data)

client.post(f"/captains/{soval['id']}", data={"action": "restore"})
check("restored", by_name("Soval")["active"] == 1)

print("\ndeleting")
tuvok = by_name("Tuvok")
check("unused captain can be deleted",
      client.post(f"/captains/{tuvok['id']}",
                  data={"action": "delete"}).status_code == 302)
check("gone from the list", by_name("Tuvok") is None)

used = by_name("Kirk")
r = client.post(f"/captains/{used['id']}", data={"action": "delete"},
                follow_redirects=True)
check("used captain cannot be deleted", b"Retire it instead" in r.data)
check("still present", by_name("Kirk") is not None)
check("its games survived", db.captain_usage().get("Kirk") == 1)

r = client.post("/captains/999999", data={"action": "delete"}, follow_redirects=True)
check("unknown id handled", b"No such captain" in r.data)

r = client.post(f"/captains/{used['id']}", data={"action": "sabotage"},
                follow_redirects=True)
check("unknown action rejected", b"Unknown action" in r.data)

print("\nmigration")
legacy = os.path.join(TMP, "legacy.db")
conn = sqlite3.connect(legacy)
conn.executescript("""
CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL, created_at TEXT NOT NULL);
INSERT INTO users (username, password_hash, created_at)
VALUES ('old', 'x', '2026-01-01'), ('newer', 'y', '2026-02-01');
""")
conn.commit()
conn.row_factory = sqlite3.Row
db._migrate(conn)
conn.commit()
rows = conn.execute("SELECT username, is_admin FROM users ORDER BY id").fetchall()
check("migration adds the column", "is_admin" in rows[0].keys())
check("oldest account becomes admin", rows[0]["is_admin"] == 1)
check("other accounts do not", rows[1]["is_admin"] == 0)
db._migrate(conn)
check("migration is idempotent",
      conn.execute("SELECT COUNT(*) FROM users WHERE is_admin = 1").fetchone()[0] == 1)
conn.close()

shutil.rmtree(TMP, ignore_errors=True)
print()
if failures:
    print(f"{len(failures)} check(s) failed: {', '.join(failures)}")
    raise SystemExit(1)
print("all checks passed")
