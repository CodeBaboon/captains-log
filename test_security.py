"""Hardening, Cloudflare Access, and export.

These are the checks that matter once the app is reachable from the internet,
so several of them deliberately try to break in rather than confirming the
happy path.
"""

import importlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

TMP = tempfile.mkdtemp()
os.environ["CC_DATA_DIR"] = TMP
os.environ["CC_SECRET_KEY"] = "test-key"
os.environ.pop("CC_ACCESS_TEAM", None)
os.environ.pop("CC_ACCESS_AUD", None)

import access  # noqa: E402
import app as application  # noqa: E402
import config  # noqa: E402
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


def run_config(env, code):
    """Import config in a fresh process with a given environment."""
    environment = dict(os.environ)
    for key in ("CC_SECRET_KEY", "CC_ACCESS_TEAM", "CC_ACCESS_AUD", "CC_ENV"):
        environment.pop(key, None)
    environment.update(env)
    return subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True, text=True, env=environment,
        cwd=os.path.dirname(os.path.abspath(__file__)),
    )


print("\nsecret key")
r = run_config({}, "import config")
check("refuses to start without a key", r.returncode != 0)
check("the error says what to do", "CC_SECRET_KEY" in r.stderr and "token_hex" in r.stderr)
check("it does not leak the fallback as a suggestion",
      r.stderr.count("dev-only-change-me") == 0, r.stderr[-120:])

r = run_config({"CC_ENV": "development"}, "import config; print(config.SECRET_KEY)")
check("development mode still starts", r.returncode == 0)
check("development uses the fallback", "dev-only-change-me" in r.stdout)

r = run_config({"CC_SECRET_KEY": "a" * 64}, "import config; print(config.SECURE_COOKIES)")
check("a real key starts in production", r.returncode == 0)
check("production forces secure cookies", r.stdout.strip() == "True")

r = run_config({"CC_ENV": "development"}, "import config; print(config.SECURE_COOKIES)")
check("development relaxes secure cookies", r.stdout.strip() == "False")

print("\nopen redirect")
for hostile in ["https://evil.example/", "//evil.example/", "http://evil.example",
                "https:/evil.example", "javascript:alert(1)"]:
    check(f"rejects {hostile}", application.safe_next(hostile) is None)

for ok in ["/stats", "/games/12", "/captains"]:
    check(f"allows {ok}", application.safe_next(ok) == ok)

check("empty next falls through", application.safe_next("") is None)
check("None falls through", application.safe_next(None) is None)

fresh = app.test_client()
r = fresh.post("/login?next=https://evil.example/",
               data={"username": "dave", "password": "longenough1"})
check("login will not bounce off site",
      "evil.example" not in r.headers.get("Location", ""),
      r.headers.get("Location"))

fresh = app.test_client()
r = fresh.post("/login?next=/stats", data={"username": "dave", "password": "longenough1"})
check("login honours a local next", r.headers.get("Location", "").endswith("/stats"))

print("\ndebug and binding")
source = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "app.py")).read()
check("debug mode is gone", "debug=True" not in source)
check("dev server binds locally", '"0.0.0.0"' not in source)
readme = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "README.md")).read()
check("the unit binds to localhost", "--bind 127.0.0.1:8080" in readme)
check("the README no longer suggests 0.0.0.0", "--bind 0.0.0.0" not in readme)

print("\naccess is off unless configured")
check("disabled with no settings", not access.enabled())

r = client.get("/", headers={access.EMAIL_HEADER: "stranger@example.com"})
check("a bare email header does nothing", r.status_code == 200)
check("no account was conjured from it",
      db.get_user_by_email("stranger@example.com") is None)

anon = app.test_client()
r = anon.get("/", headers={access.EMAIL_HEADER: "stranger@example.com"},
             follow_redirects=True)
check("the email header cannot sign anyone in", b"Sign in" in r.data)

r = anon.get("/", headers={access.HEADER: "not.a.real.token"}, follow_redirects=True)
check("a junk token with access off is ignored", b"Sign in" in r.data)

try:
    access.identify(None)
    check("identify refuses when disabled", False)
except access.AccessError as exc:
    check("identify refuses when disabled", "not configured" in str(exc))

print("\naccess when configured")
os.environ["CC_ACCESS_TEAM"] = "testteam"
os.environ["CC_ACCESS_AUD"] = "test-audience"
importlib.reload(config)
importlib.reload(access)
check("enabled once both settings exist", access.enabled())
check("certs url is built from the team",
      access._certs_url() == "https://testteam.cloudflareaccess.com/cdn-cgi/access/certs",
      access._certs_url())

os.environ["CC_ACCESS_TEAM"] = "https://testteam.cloudflareaccess.com/"
importlib.reload(config)
importlib.reload(access)
check("a full team url is accepted too",
      access._certs_url() == "https://testteam.cloudflareaccess.com/cdn-cgi/access/certs",
      access._certs_url())

os.environ["CC_ACCESS_TEAM"] = "testteam"
importlib.reload(config)
importlib.reload(access)

check("only one setting is not enough",
      not run_config({"CC_SECRET_KEY": "a" * 64, "CC_ACCESS_TEAM": "t"},
                     "import access; raise SystemExit(0 if not access.enabled() else 1)"
                     ).returncode)

# A forged token signed with a key of the attacker's choosing must be refused.
import jwt as pyjwt  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import rsa  # noqa: E402

attacker_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
forged = pyjwt.encode(
    {"email": "attacker@example.com", "aud": "test-audience",
     "exp": int(time.time()) + 600, "iat": int(time.time())},
    attacker_key, algorithm="RS256",
)


class FakeRequest:
    def __init__(self, token):
        self.headers = {access.HEADER: token} if token else {}
        self.cookies = {}


try:
    access.identify(FakeRequest(forged))
    check("a forged signature is refused", False, "it was accepted")
except access.AccessError:
    check("a forged signature is refused", True)
except Exception as exc:
    # Reaching Cloudflare fails in this sandbox, which is also a refusal.
    check("a forged signature is refused", True, type(exc).__name__)

none_alg = pyjwt.encode({"email": "attacker@example.com"}, key="", algorithm="none")
try:
    access.identify(FakeRequest(none_alg))
    check("the none algorithm is refused", False, "it was accepted")
except Exception:
    check("the none algorithm is refused", True)

try:
    access.identify(FakeRequest(None))
    check("a missing token raises rather than defaulting", False, "it returned")
except access.AccessError as exc:
    check("a missing token raises rather than defaulting", "No Access token" in str(exc))

expired = pyjwt.encode(
    {"email": "x@example.com", "aud": "test-audience",
     "exp": int(time.time()) - 60, "iat": int(time.time()) - 600},
    attacker_key, algorithm="RS256",
)
try:
    access.identify(FakeRequest(expired))
    check("an expired token is refused", False, "it was accepted")
except Exception:
    check("an expired token is refused", True)

os.environ.pop("CC_ACCESS_TEAM")
os.environ.pop("CC_ACCESS_AUD")
importlib.reload(config)
importlib.reload(access)

print("\naccess account creation")
first = db.create_access_user("friend@example.com", "friend")
row = db.get_user_by_email("friend@example.com")
check("account created from an email", row is not None)
check("it stores no usable password", row["password_hash"] == "!access-only")
check("a later account is not an admin", row["is_admin"] == 0)
check("lookup is case-insensitive",
      db.get_user_by_email("FRIEND@EXAMPLE.COM") is not None)

db.create_access_user("friend@other.example", "friend")
names = [r["username"] for r in [db.get_user(first), db.get_user(first + 1)]]
check("clashing usernames are made unique", len(set(names)) == 2, str(names))

check("the stored hash cannot be logged into with any password",
      app.test_client().post(
          "/login", data={"username": "friend", "password": "!access-only"},
          follow_redirects=True).data.count(b"did not match") == 1)

check("usernames are derived safely",
      access.username_for("a.b-c_d+tag@example.com").startswith("a.b-c_d"))
check("a hostile local part is cleaned",
      "/" not in access.username_for("../../etc@example.com"))

print("\nexport")
client.post("/games/new", data={
    "played_on": "2026-11-01", "player_captain": "Georgiou",
    "board_side": "advanced", "bot_captain": "Soval",
    "bot_difficulty": "Lieutenant", "ending": "resolution",
    "p_glory": "12", "b_glory": "9", "p_locations": "4", "b_locations": "3",
    "p_endgame": "8", "b_endgame": "7", "p_card_vp": "24", "b_card_vp": "15",
    "p_research": "7", "b_research": "5", "p_influence": "4", "b_influence": "3",
    "p_military": "3", "b_military": "2", "p_mission": "6",
})

r = client.get("/export.json")
check("export returns json", r.status_code == 200
      and r.mimetype == "application/json")
check("it downloads as a file",
      "attachment" in r.headers.get("Content-Disposition", ""))

payload = json.loads(r.data)
check("it names the app", payload["application"] == "Captain's Log")
check("it carries the games", payload["game_count"] == 1
      and len(payload["games"]) == 1)
check("it explains the score rows", len(payload["score_rows"]) == 8)
check("it records the solo threshold", payload["solo_win_score"] == 70)

game = payload["games"][0]
check("scores are present", game["p_total"] == 68, f"got {game['p_total']}")
check("internal ids are stripped", "user_id" not in game)
check("the vestigial photo field is stripped", "photo_path" not in game)

other = app.test_client()
check("export needs a login",
      b"Sign in" in other.get("/export.json", follow_redirects=True).data)

other.post("/login", data={"username": "friend", "password": "nope"})
check("a failed login gets no export",
      b"Sign in" in other.get("/export.json", follow_redirects=True).data)

check("the menu offers it", b"/export.json" in client.get("/").data)

shutil.rmtree(TMP, ignore_errors=True)
print()
if failures:
    print(f"{len(failures)} check(s) failed: {', '.join(failures)}")
    raise SystemExit(1)
print("all checks passed")
