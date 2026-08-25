"""Titles, breadcrumbs, and the icon set."""

import json
import os
import re
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

failures = []


def check(label, condition, detail=""):
    if condition:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label} {detail}")
        failures.append(label)


def title_of(path):
    html = client.get(path).data.decode()
    match = re.search(r"<title>(.*?)</title>", html, re.S)
    return match.group(1).strip() if match else None


def crumbs_of(path):
    html = client.get(path).data.decode()
    block = re.search(r'<nav class="crumbs".*?</nav>', html, re.S)
    if not block:
        return None
    return re.findall(r'>([^<>]+)</(?:a|span)>', block.group(0))


print("\ntitles")
check("setup page titled", title_of("/setup") == "First run | Captain's Log",
      title_of("/setup"))

client.post("/setup", data={"username": "dave", "password": "longenough1"})
client.post("/games/new", data={
    "played_on": "2026-08-24", "player_captain": "Georgiou",
    "board_side": "advanced", "bot_captain": "Soval",
    "bot_difficulty": "Lieutenant", "ending": "resolution",
    "p_glory": "4", "b_glory": "18", "p_locations": "3", "b_locations": "2",
    "p_endgame": "8", "b_endgame": "10", "p_card_vp": "32", "b_card_vp": "4",
    "p_research": "8", "b_research": "2", "p_influence": "2", "b_influence": "4",
    "p_military": "6", "b_military": "0", "p_mission": "6",
})

check("home has no suffix", title_of("/") == "Captain's Log", title_of("/"))
check("home capitalised", title_of("/") == "Captain's Log")
check("stats titled", title_of("/stats") == "Stats | Captain's Log", title_of("/stats"))
check("captain titled", title_of("/captain/Georgiou") == "Georgiou | Captain's Log",
      title_of("/captain/Georgiou"))
check("new game titled", title_of("/games/new") == "New game | Captain's Log",
      title_of("/games/new"))
check("edit titled", title_of("/games/1/edit") == "Edit game | Captain's Log",
      title_of("/games/1/edit"))
check("game detail titled",
      title_of("/games/1") == "Georgiou v Soval | Captain's Log",
      title_of("/games/1"))
check("separator is a pipe", "|" in title_of("/stats"))
check("no em dash anywhere", "\u2014" not in title_of("/stats"))

print("\nbreadcrumbs")
check("home has no crumbs", crumbs_of("/") is None)
check("stats crumbs", crumbs_of("/stats")[-2:] == ["Log", "Stats"],
      str(crumbs_of("/stats")))
check("captain crumbs three deep",
      crumbs_of("/captain/Georgiou")[-3:] == ["Log", "Stats", "Georgiou"],
      str(crumbs_of("/captain/Georgiou")))
check("new game crumbs", crumbs_of("/games/new")[-2:] == ["Log", "New game"],
      str(crumbs_of("/games/new")))
check("game detail crumbs",
      crumbs_of("/games/1")[-2:] == ["Log", "Georgiou v Soval"],
      str(crumbs_of("/games/1")))
check("login has no crumbs", crumbs_of("/login") is None)

html = client.get("/captain/Georgiou").data.decode()
check("back chevron points at the parent",
      re.search(r'class="crumb-back" href="/stats\?side=you"', html) is not None)
check("current page is not a link",
      '<span aria-current="page">Georgiou</span>' in html)
check("parent crumbs are links", 'href="/stats?side=you">Stats</a>' in html)

html = client.get("/captain/Soval?side=bot").data.decode()
crumb_block = re.search(r'<nav class="crumbs".*?</nav>', html, re.S).group(0)
check("bot perspective carried into the stats crumb",
      'href="/stats?side=bot"' in crumb_block, crumb_block[:160])
check("bot back chevron carries the perspective",
      'class="crumb-back" href="/stats?side=bot"' in html)

print("\nredundant links removed")
check("stats has no bottom back link",
      b"Back to the log" not in client.get("/stats").data)
check("captain has no bottom back link",
      b"Back to stats" not in client.get("/captain/Georgiou").data)
check("game detail has no bottom back link",
      b"Back to the log" not in client.get("/games/1").data)

print("\nicons")
for name, kind in [("favicon.svg", b"<svg"), ("icon-32.png", b"\x89PNG"),
                   ("icon-192.png", b"\x89PNG"), ("icon-512.png", b"\x89PNG"),
                   ("apple-touch-icon.png", b"\x89PNG")]:
    r = client.get(f"/static/icons/{name}")
    check(f"{name} served", r.status_code == 200 and r.data.startswith(kind),
          f"status {r.status_code}")

html = client.get("/").data.decode()
check("svg favicon linked", 'rel="icon" type="image/svg+xml"' in html)
check("png favicon linked", 'sizes="32x32"' in html)
check("apple touch icon linked", 'rel="apple-touch-icon"' in html)

manifest = json.loads(client.get("/static/manifest.json").data)
check("manifest names the app", manifest["name"] == "Captain's Log")
check("manifest lists icons", len(manifest["icons"]) >= 2)
check("manifest has a 192 icon",
      any(i.get("sizes") == "192x192" for i in manifest["icons"]))
check("manifest has a 512 icon",
      any(i.get("sizes") == "512x512" for i in manifest["icons"]))
for icon in manifest["icons"]:
    r = client.get(icon["src"])
    check(f"manifest icon {icon['src']} resolves", r.status_code == 200)

shutil.rmtree(TMP, ignore_errors=True)
print()
if failures:
    print(f"{len(failures)} check(s) failed: {', '.join(failures)}")
    raise SystemExit(1)
print("all checks passed")
