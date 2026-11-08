"""Settings and the player admin page.

The important checks here are the refusals: an account cannot be left without
an administrator, a rename cannot collide, an email cannot be claimed twice,
and deleting an account cannot take game history with it.
"""

import os
import shutil
import tempfile

TMP = tempfile.mkdtemp()
os.environ["CC_DATA_DIR"] = TMP
os.environ["CC_SECRET_KEY"] = "test-key"

import app as application  # noqa: E402
import db  # noqa: E402

app = application.app
app.config["TESTING"] = True
client = app.test_client()
client.post("/setup", data={"username": "Dave", "password": "longenough1"})

failures = []


def check(label, condition, detail=""):
    if condition:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label} {detail}")
        failures.append(label)


def by_name(name):
    return next((u for u in db.list_users() if u["username"] == name), None)


def log_a_game(as_client=None):
    (as_client or client).post("/games/new", data={
        "played_on": "2026-11-01", "player_captain": "Georgiou",
        "board_side": "advanced", "bot_captain": "Soval",
        "bot_difficulty": "Lieutenant", "ending": "resolution",
        "p_glory": "12", "b_glory": "9", "p_locations": "4", "b_locations": "3",
        "p_endgame": "8", "b_endgame": "7", "p_card_vp": "24", "b_card_vp": "15",
        "p_research": "7", "b_research": "5", "p_influence": "4",
        "b_influence": "3", "p_military": "3", "b_military": "2", "p_mission": "6",
    })


print("\nsettings")
r = client.get("/settings")
check("page renders", r.status_code == 200 and b"Display name" in r.data)
check("it shows the current name", b'value="Dave"' in r.data)
check("it links the export", b"/export.json" in r.data)

client.post("/settings", data={"username": "Captain Dave"})
check("name changed", db.get_user(1)["username"] == "Captain Dave")
check("the menu follows", b"Captain Dave" in client.get("/").data)

r = client.post("/settings", data={"username": "   "}, follow_redirects=True)
check("blank name rejected", b"Enter a name" in r.data)
check("name unchanged", db.get_user(1)["username"] == "Captain Dave")

r = client.post("/settings", data={"username": "x" * 41}, follow_redirects=True)
check("overlong name rejected", b"too long" in r.data)

client.post("/settings", data={"username": "Dave"})

print("\nplayers page")
r = client.get("/users")
check("admin sees it", r.status_code == 200 and b"Dave" in r.data)
check("the admin badge shows", b"Admin" in r.data)
check("the menu offers it", b"/users" in client.get("/").data)

friend_id = db.create_access_user("friend@example.com", "friend")
friend = app.test_client()
friend.post("/login", data={"username": "friend", "password": "anything"})

check("an access account cannot use the password form",
      b"Sign in" in friend.get("/settings", follow_redirects=True).data)

# Sign the friend in the way the app would, by their session.
with friend.session_transaction() as s:
    s["user_id"] = friend_id

check("a player sees their own settings",
      friend.get("/settings").status_code == 200)
check("a player cannot see the players page",
      friend.get("/users").status_code == 403)
check("a player cannot edit anyone",
      friend.post("/users/1", data={"action": "promote"}).status_code == 403)
check("the menu hides it from players",
      b"/users" not in friend.get("/").data)

print("\nemail changes")
client.post("/users/1", data={"action": "email", "email": "dave@example.com"})
check("email set", db.get_user(1)["email"] == "dave@example.com")
check("lookup finds it", db.get_user_by_email("dave@example.com") is not None)

client.post("/users/1", data={"action": "email", "email": "NEW@Example.COM"})
check("email is stored lowercase", db.get_user(1)["email"] == "new@example.com")
check("the old address no longer matches",
      db.get_user_by_email("dave@example.com") is None)
check("the account kept its identity", db.get_user(1)["username"] == "Dave")

r = client.post("/users/1", data={"action": "email", "email": "friend@example.com"},
                follow_redirects=True)
check("an email cannot be claimed twice", b"already belongs to" in r.data)
check("the clash changed nothing", db.get_user(1)["email"] == "new@example.com")

client.post("/users/1", data={"action": "email", "email": ""})
check("an email can be cleared", db.get_user(1)["email"] is None)
client.post("/users/1", data={"action": "email", "email": "dave@example.com"})

# The whole point: an address change keeps the history.
log_a_game()
before = db.count_games(1)
client.post("/users/1", data={"action": "email", "email": "dave@newhost.example"})
check("games survive an email change", db.count_games(1) == before and before > 0)
check("the new address resolves to the same account",
      db.get_user_by_email("dave@newhost.example")["id"] == 1)

print("\nrenaming")
client.post(f"/users/{friend_id}", data={"action": "rename", "username": "Jim"})
check("admin can rename a player", db.get_user(friend_id)["username"] == "Jim")

r = client.post(f"/users/{friend_id}", data={"action": "rename", "username": "dave"},
                follow_redirects=True)
check("a clashing name is refused, ignoring case", b"already taken" in r.data)
check("the name did not change", db.get_user(friend_id)["username"] == "Jim")

print("\nadmin rights")
check("only one admin to start",
      len([u for u in db.list_users() if u["is_admin"]]) == 1)

r = client.post("/users/1", data={"action": "demote"}, follow_redirects=True)
check("the last admin cannot step down", b"only administrator" in r.data)
check("they are still an admin", db.get_user(1)["is_admin"] == 1)

client.post(f"/users/{friend_id}", data={"action": "promote"})
check("a player can be promoted", db.get_user(friend_id)["is_admin"] == 1)
check("the promoted account can now manage",
      friend.get("/users").status_code == 200)

client.post("/users/1", data={"action": "demote"})
check("now the first admin can step down", db.get_user(1)["is_admin"] == 0)
check("and loses access", client.get("/users").status_code == 403)

# Put it back so the rest of the suite can manage.
db.set_user_admin(1, True)
db.set_user_admin(friend_id, False)

print("\ndeleting")
check("an account with games cannot be deleted",
      b"would take the history" in
      client.post("/users/1", data={"action": "delete"},
                  follow_redirects=True).data)
check("it is still there", db.get_user(1) is not None)

spare = db.create_access_user("spare@example.com", "spare")
client.post(f"/users/{spare}", data={"action": "delete"})
check("an empty account can be deleted", db.get_user(spare) is None)

r = client.post("/users/999999", data={"action": "delete"}, follow_redirects=True)
check("unknown account handled", b"No such account" in r.data)

r = client.post("/users/1", data={"action": "sabotage"}, follow_redirects=True)
check("unknown action rejected", b"Unknown action" in r.data)

print("\nseparation holds")
mine_before = db.count_games(1)
log_a_game(friend)
check("logging a game does not touch another account",
      db.count_games(1) == mine_before, f"{db.count_games(1)} vs {mine_before}")
check("the game landed on the right account", db.count_games(friend_id) == 1)
mine = {g["id"] for g in db.export_games(1)}
theirs = {g["id"] for g in db.export_games(friend_id)}
check("no game appears in both exports", not (mine & theirs))
check("both accounts have games", mine and theirs)

shutil.rmtree(TMP, ignore_errors=True)
print()
if failures:
    print(f"{len(failures)} check(s) failed: {', '.join(failures)}")
    raise SystemExit(1)
print("all checks passed")
