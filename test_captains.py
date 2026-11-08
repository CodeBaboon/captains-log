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
    return next((c for c in db.list_captains() if c["name"] == name), None)


print("\nadmin access")
r = client.get("/captains")
check("page renders for the owner",
      r.status_code == 200 and b'class="cap-add"' in r.data)
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
page = client.get("/captains").data.decode()
add_rows = page.count('class="cap-add"')
check("each group carries its own add row",
      add_rows == len(db.box_names()),
      f"{add_rows} rows for {len(db.box_names())} groups")
check("the group dropdown is gone", 'aria-label="Which group"' not in page)
check("the group is a hidden field now", 'type="hidden" name="box"' in page)
check("add rows label their group for screen readers",
      'aria-label="New captain in Second Contact"' in page)
check("add rows carry their group",
      'value="Captain&#39;s Chair"' in page and 'value="Duty and Honor"' in page)
check("a group with an apostrophe posts its real name",
      client.post("/captains", data={"name": "Archer", "box": "Captain's Chair"},
                  follow_redirects=True) is not None
      and by_name("Archer")["box"] == "Captain's Chair")

client.post("/captains", data={"name": "Janeway", "box": "Duty and Honor"})
check("captain added", by_name("Janeway") is not None)
check("box respected", by_name("Janeway")["box"] == "Duty and Honor")

r = client.post("/captains", data={"name": "janeway"}, follow_redirects=True)
check("duplicate rejected case-insensitively", b"already on the list" in r.data)
check("no second row created",
      len([c for c in db.list_captains() if c["name"].lower() == "janeway"]) == 1)

r = client.post("/captains", data={"name": "   "}, follow_redirects=True)
check("blank name rejected", b"Enter a name" in r.data)

r = client.post("/captains", data={"name": "x" * 61}, follow_redirects=True)
check("overlong name rejected", b"too long" in r.data)

r = client.post("/captains", data={"name": "Tuvok", "box": "Nonsense"},
                follow_redirects=True)
check("unknown group rejected", b"Pick a group" in r.data)
check("captain not created", by_name("Tuvok") is None)

client.post("/captains", data={"name": "Tuvok", "box": "Second Contact"})
check("captain lands in its group", by_name("Tuvok")["box"] == "Second Contact")

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
            data={"action": "rename", "name": "Kirk", "box": "Second Contact"})
check("box changed", by_name("Kirk")["box"] == "Second Contact")

# An unknown group must leave the captain where it was rather than blanking it.
client.post(f"/captains/{kirk['id']}",
            data={"action": "rename", "name": "Kirk", "box": "Nonexistent"})
check("unknown group on rename is ignored",
      by_name("Kirk")["box"] == "Second Contact", by_name("Kirk")["box"])
check("games untouched by a box change",
      db.captain_usage().get("Kirk") == 1, str(db.captain_usage()))

print("\nalways pickable")
soval = by_name("Soval")
check("every captain is offered on a new game",
      b'value="Soval"' in client.get("/games/new").data)

target = next(r for r in db.list_games(1) if r["bot_captain"] == "Soval")
check("and on an edit",
      b'value="Soval"' in client.get(f"/games/{target['id']}/edit").data)

check("no retire action remains",
      client.post(f"/captains/{soval['id']}", data={"action": "retire"},
                  follow_redirects=True).data.count(b"Unknown action") == 1)
check("Soval survived that", by_name("Soval") is not None)
check("still usable after an unknown action",
      db.captain_exists("Soval") == "Soval")

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

print("\ngroups")
names = db.box_names()
check("seeded groups present",
      names == ["Captain's Chair", "To Boldly Go", "Second Contact",
                "Resistance is Futile", "Duty and Honor"], str(names))
check("old labels gone", "Expansion" not in names and "Other" not in names)

page = client.get("/captains").data.decode()
check("empty groups still render with an add row",
      page.count('class="cap-add"') == len(db.box_names()))
check("empty groups offer deletion", "Delete group" in page)

client.post("/captains/groups", data={"name": "Mirror Universe"})
check("group added", "Mirror Universe" in db.box_names())
check("new group is offered when adding a captain",
      b"Mirror Universe" in client.get("/captains").data)

r = client.post("/captains/groups", data={"name": "mirror universe"},
                follow_redirects=True)
check("duplicate group rejected", b"already a group" in r.data)
check("no second group", db.box_names().count("Mirror Universe") == 1)

r = client.post("/captains/groups", data={"name": "  "}, follow_redirects=True)
check("blank group rejected", b"Enter a group name" in r.data)

r = client.post("/captains/groups", data={"name": "x" * 61}, follow_redirects=True)
check("overlong group rejected", b"too long" in r.data)

mirror = next(b for b in db.list_boxes() if b["name"] == "Mirror Universe")
client.post("/captains", data={"name": "Mirror Kirk", "box": "Mirror Universe"})
r = client.post(f"/captains/groups/{mirror['id']}/delete", follow_redirects=True)
check("group with captains cannot be deleted", b"still has 1 captain" in r.data)
check("group survived", "Mirror Universe" in db.box_names())

client.post(f"/captains/{by_name('Mirror Kirk')['id']}", data={"action": "delete"})
r = client.post(f"/captains/groups/{mirror['id']}/delete", follow_redirects=True)
check("empty group deleted", "Mirror Universe" not in db.box_names())

r = client.post("/captains/groups/999999/delete", follow_redirects=True)
check("unknown group handled", b"No such group" in r.data)

check("non-admin cannot add a group",
      other.post("/captains/groups", data={"name": "Nope"}).status_code == 403)
check("non-admin cannot delete a group",
      other.post(f"/captains/groups/1/delete").status_code == 403)
check("that attempt changed nothing", "Nope" not in db.box_names())

# A group deleted on purpose must not come back on the next start.
db.init_db()
check("seeding does not resurrect a deleted group",
      "Mirror Universe" not in db.box_names())

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

# A database whose captains sit in groups the seed list never had must keep
# them, or those captains would vanish from every dropdown.
conn.executescript("""
CREATE TABLE boxes (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE);
CREATE TABLE captains (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE,
                       box TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1);
INSERT INTO captains (name, box) VALUES ('Legacy One', 'Expansion'),
                                        ('Legacy Two', 'Other');
""")
conn.commit()
db._seed_boxes(conn)
conn.commit()
legacy_names = [r["name"] for r in conn.execute("SELECT name FROM boxes ORDER BY id")]
check("seed list applied to the empty table",
      legacy_names[:5] == db.SEED_BOXES, str(legacy_names))
check("legacy groups adopted",
      "Expansion" in legacy_names and "Other" in legacy_names, str(legacy_names))
db._seed_boxes(conn)
check("adoption is idempotent",
      len([r for r in conn.execute("SELECT name FROM boxes")]) == len(legacy_names))
conn.close()

shutil.rmtree(TMP, ignore_errors=True)
print()
if failures:
    print(f"{len(failures)} check(s) failed: {', '.join(failures)}")
    raise SystemExit(1)
print("all checks passed")
