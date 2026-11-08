# Captain's Log

A solo game log for Star Trek: Captain's Chair. Photograph the scorepad, check
what it read, save. Or type it in by hand.

Built to sit on a Raspberry Pi on your LAN. Flask, SQLite, and one outbound API
call when you scan a sheet. No compiled dependencies beyond Pillow.

## What it records

Per game: date, your captain, board side, the bot's captain and rank, how the
game ended, the eight score rows for both sides, and computed totals.

Scoresheet photos are not stored. A photo is sent to the API, the numbers come
back and fill the form, and the file is discarded. The `games.photo_path`
column is vestigial, left in the schema so old and new databases match. The
file input on the form deliberately has no `name`, so the browser does not
upload the photo a second time when the game is saved.

Four rules are enforced in `_parse_game_form`:

- **Cadet has no opponent.** At that rank there is no bot, so the bot captain
  field and the whole bot column disappear. You win by reaching a target score
  instead, 70 by default and hitting it exactly counts as a win. Override with
  `CC_SOLO_WIN_SCORE`. The Burn still applies and is still a loss.


- **No draws against the bot.** You need strictly more points; equal totals is a
  loss.
- **Mission points need the Advanced side.** On Basic the row is disabled and
  stored as null, not zero, so it renders as a dash rather than a real score.
- **The Burn is a loss with no score.** Selecting it hides the grid and stores
  nulls, because you would not have written the scores down.

Card VP accepts negatives, which is how Incidents land in the total.

Rank has no default and must be chosen before a game can be saved, since it
determines whether there is an opponent at all.

One schema wart: `bot_captain` is `NOT NULL`, so a solo game stores an empty
string rather than null. Templates treat the empty string as "no opponent".
Changing the column would mean rebuilding the table on live data, which is not
worth it for this.

## Running it locally

```bash
pip install -r requirements.txt
export CC_ENV=development
export ANTHROPIC_API_KEY="sk-ant-..."
python3 app.py
```

`CC_ENV=development` lets the app start without a secret key and relaxes the
secure-cookie requirement so sessions work over plain HTTP. Anywhere else the
app refuses to start without `CC_SECRET_KEY`, because the fallback key is
published in this repository and anyone could forge a session with it.

Open http://localhost:8080. The first visit sends you to `/setup` to create your
account; that page stops working once an account exists.

Without an API key everything works except scanning, which reports that it is
unconfigured and leaves you to type the game in.

## Installing on the Pi

```bash
sudo apt install python3-pip python3-venv
git clone <your repo> /opt/captains-log
cd /opt/captains-log
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

If Pillow tries to build from source, `sudo apt install python3-pil` first and
create the venv with `--system-site-packages`; piwheels usually has a prebuilt
wheel on Raspberry Pi OS.

Create `/etc/captains-log.env`, readable only by root:

```
CC_SECRET_KEY=<64 hex characters>
ANTHROPIC_API_KEY=sk-ant-...
CC_DATA_DIR=/var/lib/captains-log
```

Then `/etc/systemd/system/captains-log.service`:

```ini
[Unit]
Description=Captain's Log
After=network-online.target

[Service]
User=pi
EnvironmentFile=/etc/captains-log.env
WorkingDirectory=/opt/captains-log
ExecStart=/opt/captains-log/.venv/bin/gunicorn \
    --workers 2 --threads 2 --timeout 120 \
    --bind 127.0.0.1:8080 app:app
Restart=on-failure

NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/var/lib/captains-log

[Install]
WantedBy=multi-user.target
```

```bash
sudo mkdir -p /var/lib/captains-log
sudo chown pi:pi /var/lib/captains-log
sudo systemctl enable --now captains-log
```

Two workers with two threads each is comfortable on a Pi 3. The 120 second
timeout exists because a scan waits on the API.

Binding to `127.0.0.1` rather than `0.0.0.0` means only something on the Pi
itself can reach the app. Reach it from elsewhere through the Cloudflare Tunnel
or Tailscale, not by listening on every interface.

Do not forward a port for this. With the app bound to localhost, reach it
through the tunnel or over Tailscale. If you later want it from outside, put Tailscale on the Pi
under your personal account rather than opening the router.

### Add it to your phone

Visit the address in mobile Safari or Chrome and choose "Add to home screen".
The manifest makes it open without browser chrome.

## Stats page

At `/stats`, linked from the log. Everything is server-rendered — the charts are
inline SVG and CSS bars, so there is no charting library and nothing to load on
a Pi.

### Filters

State lives entirely in the query string, so any view is a bookmarkable URL:
`/stats?side=you&captain=Georgiou&captain=Kirk&rank=Lieutenant`.

An empty selection in a group means "no filter" rather than "nothing", so
clearing a group cannot strand you on a blank page. Unrecognised values are
dropped rather than erroring. Captains sit behind a collapsed summary rather
than a pill row, because pills stop scaling somewhere around a dozen options.

Filters apply on submit rather than on every click. With multi-select that
matters — auto-submitting would reload the page between each captain you tick.

### The You / Bot toggle

This is not a straight swap, because the bot is not symmetrical with you:

- The bot never scores Mission, so that row disappears rather than showing zero.
- Cadet games have no bot at all, so they drop out of the sample entirely. The
  header count says so: "6 of 6" rather than "6 of 7".
- Cadet vanishes from both the rank filter and the win rate panel.
- The toggle also changes what the captain filter means, from your captain to
  the bot's.

The win rate panel is a mirror in bot view, since the bot's win rate is exactly
your loss rate. It is relabelled rather than hidden, so the number is never
ambiguous about whose it is.

### Record by captain

A sortable table directly under the headline chips. Default order is most wins
first, tie-broken by win rate then name, so the order is deterministic rather
than depending on how rows came out of the database.

The server always renders it sorted; the column sorting is client-side and a
progressive enhancement, so it still makes sense with JavaScript off. Headers
are real buttons inside `th` elements with `aria-sort`, keyboard reachable, and
at least 34px tall so they are tappable on a phone.

Two sorting details worth keeping: captains with no scored games have no
average or best, and those blanks sort last in both directions rather than
being treated as zero. Ties always fall back to captain name, so repeated
clicks never reshuffle equal rows.

Solo games fold into the record. At Cadet a game is won or lost against the
target score, so it counts like any other result, and the page filters can
exclude Cadet if you want them out.

### Why composition rather than stacked averages

The scoring shape panel stacks each captain's *share* of their own total, not
raw averages. Averages do not sum: stacking one captain's 20 on another's 14
gives 34, which describes no game that was ever played, and the highest-scoring
captain would bury the rest. Shares sum to 100, so every bar is the same length
and the shapes are directly comparable. The raw average sits at the right so
the magnitude that normalising discards is still visible.

Sample sizes are spelled out rather than using n-notation: the scoring shape
panel says "5 games", and the win rate panel puts the record inside the bar
itself, so the bar length carries the rate and the label carries the sample.
The label is always pinned to the right edge so every row lines up; only its
colour changes, going dark once the fill reaches far enough to sit under it.

Every captain with a scored game appears, including one-game captains, since
the game count travels with each row. Negative Card VP is clamped
to zero for the width calculation only — a negative slice has no sensible width
— while the reported average stays truthful.

## Captain detail

At `/captain/<name>`, reached by clicking a captain in the scoring shape panel.
The perspective carries through in the link, so clicking a captain while in bot
view shows their games as the bot.

Four panels. Three are filtered views of what the stats page already computes:
headline numbers, record against each opponent, and a rank ladder. The one that
earns the page is **against your baseline**.

That panel shows each category as points above or below your average across
every captain. Absolute averages cannot answer "what is different about this
captain" without holding your overall numbers in your head; the difference can.
Bars diverge from a centre line, the largest swing fills half the track, and the
raw average sits beneath each figure so the magnitude is not lost.

Solo games collect under their own heading in the opponent list rather than
being dropped, and sort last since they are not really a matchup.

A captain with no games returns 404 rather than an empty page, since there is
nothing to say about a captain you have never played.

## Navigation and titles

The account menu is the right-hand cap of the divider bar, so it costs no extra
row and appears on every signed-in page. The panel drops downward over the
content, which is the point: an earlier version sat at the foot of the page and
its options opened below the fold.

When the cap is present the parent carries a `divider-has-menu` class and the
bar squares off its right end, so the cap supplies the rounded finish and the
two read as one element. A class rather than `:has()`, so nothing depends on
selector support. Without a cap, the bar keeps its own curve.

The top divider is 16px rather than 12px so a name fits in the cap, and the
cap's hit area reaches 12px above and below via a pseudo-element, since a 16px
strip is too thin to tap reliably. Dividers inside panels stay at 12px.

It is a `<details>`, so it works without JavaScript; `menu.js` only adds
closing on an outside click or Escape. Signing out asks for confirmation,
because the control is now one tap from every page.

A context processor exposes `current_user`, reusing the row `login_required`
already loaded rather than issuing another query. The Manage captains link only
renders for administrators, and the route checks independently.


Every page except the log and the auth screens defines two things at the top of
its template: `page_title` and `crumbs`. Base renders both, so adding a page
means adding two `set` lines rather than touching the layout.

Titles are `Page | Captain's Log`, with the log itself just `Captain's Log`.

Breadcrumbs carry a back chevron pointing at the parent crumb, which is what
makes a deep page one tap from its parent. Query state travels with the links:
from a captain page opened in bot view, both the chevron and the Stats crumb
return you to bot view rather than resetting to your own.

The bottom "Back to" buttons are gone. They only existed because there was no
other way out of a page.

## Icons

`static/icons/` holds an SVG favicon plus 32, 180, 192 and 512 pixel PNGs, all
generated from the same geometry: three stacked pill bars in orange, mauve and
blue, matching the divider motif that appears on every screen. The shape is
paths rather than text, so nothing depends on a font loading.

The manifest references the 192 and 512 icons, which is what makes an installed
home screen shortcut show the real icon instead of a generic browser glyph.

To regenerate them, the geometry lives in the SVG; the PNG sizes were rendered
with Pillow at 4x and downsampled.

## Backups

`deploy/backup.sh` takes a weekly snapshot. It uses Python's sqlite3 backup API
rather than the `sqlite3` command line tool, which Raspberry Pi OS does not
install by default, and which a plain `cp` could not replace anyway: the
database runs in WAL mode, so recent writes can be sitting in the write-ahead
log rather than the main file.

Every backup is verified with `PRAGMA integrity_check` before it is kept, and
the script exits non-zero if the check fails, so a silently corrupt file never
masquerades as a good one.

```bash
sudo mkdir -p /var/backups/captains-log
sudo chown "$USER" /var/backups/captains-log

sudo cp deploy/captains-log-backup.service deploy/captains-log-backup.timer \
    /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now captains-log-backup.timer
```

Edit `User=` and `ExecStart=` in the service file to match your username and
checkout path. Check it works before trusting it:

```bash
sudo systemctl start captains-log-backup.service
journalctl -u captains-log-backup.service -n 20 --no-pager
systemctl list-timers captains-log-backup.timer
```

Settings, all overridable in the service file:

| Variable | Default |
| --- | --- |
| `CC_DB` | `/var/lib/captains-log/captains_log.db` |
| `CC_BACKUP_DIR` | `/var/backups/captains-log` |
| `CC_BACKUP_KEEP` | `8` |

`Persistent=true` on the timer means a backup missed while the Pi was off runs
at the next boot rather than being skipped.

**The backups are on the same SD card as the database**, which is only half a
backup: it survives a mistaken delete but not the card failing. Copy the
directory somewhere else periodically, or point `CC_BACKUP_DIR` at a mount on
another machine.

To restore, stop the service, gunzip the snapshot over the database, and start
again. Scoresheet photos are not stored, so the database is the whole of it.

## Cloudflare Access

When the app sits behind a Cloudflare Tunnel with an Access policy in front,
Cloudflare has already authenticated the visitor and signs a token into every
request. Trusting that token means no registration flow, no invite codes and no
password resets: people are invited in the Cloudflare dashboard, and a user row
is created here the first time they arrive.

Two settings turn it on, both required:

```
CC_ACCESS_TEAM=yourteam          # or yourteam.cloudflareaccess.com
CC_ACCESS_AUD=<application audience tag>
```

With either missing, Access sign-in is off entirely and the password form is
the only way in. There is no configuration in which the app trusts an
unverified header.

`access.py` verifies the JWT signature against Cloudflare's published keys and
checks the audience matches this application. It never falls back to the plain
`Cf-Access-Authenticated-User-Email` header, which is only as trustworthy as
whoever can reach the origin. A token that is present but invalid returns 403
rather than quietly showing the password form, because that would hide a broken
tunnel rather than surfacing it.

Accounts created this way store `!access-only` in place of a password hash,
which no password can produce, so they can only ever sign in through Access.
Keep your own password account as a way back in if Cloudflare is having a bad
day.

`PyJWT` and `cryptography` are needed for this. On the Pi, prefer the distro
packages over building from source:

```bash
sudo apt install python3-jwt python3-cryptography
```

## Accounts

`/settings` is for everyone: change your display name, see which email signs
you in, and export your games.

`/users` is admin only. It lists every account with the number of games it
holds, and allows four things:

- **Set the email.** This is the one that matters. It is the address Cloudflare
  Access matches on, so when someone's email changes you update the Cloudflare
  policy and then this field, and their next sign-in finds the existing account
  with all its history rather than creating an empty one. Without it, an email
  change silently orphans their games.
- **Rename.** Names stay unique, ignoring case.
- **Promote or demote.** The last administrator cannot step down, so the
  install can never be left without one.
- **Delete.** Refused while the account still holds games, since deleting would
  take the history with it.

An account's email is unique: claiming one that belongs to another account is
refused rather than silently moving it.

Accounts appear here on their own. Invite someone in Cloudflare Access and a
row shows up the first time they sign in, with a username derived from their
email that either of you can change afterwards.

## Export

`/export.json` hands the signed-in account everything it has logged, as a
download. Internal identifiers are stripped. The file includes the score row
definitions and the solo threshold, so the numbers make sense without this
codebase to read them against.

This is not a nicety once other people are using it: their data lives on one
Raspberry Pi with no account recovery, so being able to walk away with it is
the least the app owes them.

## Captains

One shared list for everyone, managed at `/captains` and seeded with the eleven
captains confirmed across both boxes, grouped by which box they came from.

Logging a game can only pick from the list. There is no inline "add a captain"
on the game form, so a typo cannot mint a phantom captain that splits the stats
later. Matching is case-insensitive: "georgiou" resolves to "Georgiou" rather
than creating a second one.

The admin page is restricted to administrators. The first account ever created
is one; `_migrate` adds the `is_admin` column to older databases and promotes
the lowest user id.

### Groups

Boxes and expansions live in their own `boxes` table, managed on the same page.
Add one when a new set comes out; delete one once no captain sits in it.

Each group ends with its own add row, so adding a captain never involves
choosing a group from a dropdown: the group is a hidden field and the section
heading is the context. The row is styled as a dimmed empty slot in the same
shape as the captain rows above it.

`_seed_boxes` fills the table only when it is empty, so a group deleted on
purpose does not reappear on the next restart. It then adopts any box value
already present on a captain, whether or not it was seeded. That matters
because grouping is what decides whether a captain appears in a dropdown at
all: an unlisted group would hide its captains from the game form, the edit
form, and the stats filter.

The seed list is Captain's Chair, To Boldly Go, Second Contact, Resistance is
Futile, and Duty and Honor.

Groups cannot be renamed yet. A typo is fixable by deleting the group while it
is empty and adding it again.

### Cloudflare Access

When the app sits behind a Cloudflare Tunnel with an Access policy in front,
Cloudflare has already authenticated the visitor and signs a token into every
request. Trusting that token means no registration flow, no invite codes and no
password resets: people are invited in the Cloudflare dashboard, and a user row
is created here the first time they arrive.

Two settings turn it on, both required:

```
CC_ACCESS_TEAM=yourteam          # or yourteam.cloudflareaccess.com
CC_ACCESS_AUD=<application audience tag>
```

With either missing, Access sign-in is off entirely and the password form is
the only way in. There is no configuration in which the app trusts an
unverified header.

`access.py` verifies the JWT signature against Cloudflare's published keys and
checks the audience matches this application. It never falls back to the plain
`Cf-Access-Authenticated-User-Email` header, which is only as trustworthy as
whoever can reach the origin. A token that is present but invalid returns 403
rather than quietly showing the password form, because that would hide a broken
tunnel rather than surfacing it.

Accounts created this way store `!access-only` in place of a password hash,
which no password can produce, so they can only ever sign in through Access.
Keep your own password account as a way back in if Cloudflare is having a bad
day.

`PyJWT` and `cryptography` are needed for this. On the Pi, prefer the distro
packages over building from source:

```bash
sudo apt install python3-jwt python3-cryptography
```

## Accounts

`/settings` is for everyone: change your display name, see which email signs
you in, and export your games.

`/users` is admin only. It lists every account with the number of games it
holds, and allows four things:

- **Set the email.** This is the one that matters. It is the address Cloudflare
  Access matches on, so when someone's email changes you update the Cloudflare
  policy and then this field, and their next sign-in finds the existing account
  with all its history rather than creating an empty one. Without it, an email
  change silently orphans their games.
- **Rename.** Names stay unique, ignoring case.
- **Promote or demote.** The last administrator cannot step down, so the
  install can never be left without one.
- **Delete.** Refused while the account still holds games, since deleting would
  take the history with it.

An account's email is unique: claiming one that belongs to another account is
refused rather than silently moving it.

Accounts appear here on their own. Invite someone in Cloudflare Access and a
row shows up the first time they sign in, with a username derived from their
email that either of you can change afterwards.

## Export

`/export.json` hands the signed-in account everything it has logged, as a
download. Internal identifiers are stripped. The file includes the score row
definitions and the solo threshold, so the numbers make sense without this
codebase to read them against.

This is not a nicety once other people are using it: their data lives on one
Raspberry Pi with no account recovery, so being able to walk away with it is
the least the app owes them.

## Captains

Two operations, each with a deliberate rule behind it:

- **Rename cascades.** Games store captain names as text, so a rename that did
  not also update `player_captain` and `bot_captain` would orphan the history
  under the old spelling. The page shows how many games a rename will touch.
- **Deleting is refused while any game references the captain.** Only genuinely
  unused entries can be removed outright, and the Delete button is only shown
  for those. To get rid of one that has games, rename it or delete those games.

Every captain on the list is always available on both the new game and edit
forms. There is no retired or inactive state.

A captain's group must exist. An unknown one is rejected when adding, and
ignored when renaming so a bad value cannot strand a captain outside every
group.

The `captains.active` column is vestigial. It is left in the schema so old and
new databases match, but nothing reads or writes it.

A scanned sheet naming a captain that is not on the list no longer drops into an
add field. The scan warns which names it could not match and leaves them for you
to resolve on the captain page.

## Scanning

`extract.py` downscales the photo to 1568px on its longest edge, sends it with a
prompt describing the fixed row order and your handwriting quirks (slashed
zeros, the diagonal for not-applicable, leading minus signs), and validates the
JSON that comes back.

The prompt also covers the Cadet case: an empty right-hand column means no bot,
and it is told not to invent a rank that is not written on the sheet.

It also sums the rows it read and compares that against the total written on the
sheet. A mismatch is surfaced as a warning above the form rather than silently
corrected, since there is no way to know which cell was misread.

Costs a fraction of a cent per game. Swap models with `CC_MODEL`.

## Tests

```bash
python3 check_syntax.py
python3 test_app.py && python3 test_stats.py && python3 test_nav.py \
  && python3 test_captains.py && python3 test_security.py \
  && python3 test_users.py
node test_sort.js   # needs jsdom: npm install jsdom
```

The first covers the scoring rules, the Burn path, negative values, validation,
auth, pagination, and the extraction parser. The second covers the stats
filters, the perspective toggle, and the aggregations, including the awkward
cases: a single data point, identical scores, and negative totals. The third
covers page titles, breadcrumb structure, and that every icon the page and
manifest reference actually resolves. `test_captains.py` covers the shared captain
list: the admin gate, the rename cascade into both game columns, that retiring
leaves an old game editable, and the `is_admin` migration. `check_syntax.py` parses every file against Python 3.11, the version Raspberry
Pi OS bookworm ships. Development on a newer Python can otherwise introduce
syntax that only fails on deployment, such as a backslash inside an f-string
expression, which 3.12 allows and 3.11 does not. `test_security.py` covers the parts that
matter once the app is on the internet, and several of its checks try to break
in rather than confirming the happy path: forged and expired Access tokens, the
`none` algorithm, off-site redirect targets, and that a bare email header
cannot sign anyone in. `test_users.py` covers settings and the
player admin page, concentrating on the refusals: the last administrator
cannot step down, an email cannot be claimed twice, and an account holding
games cannot be deleted. `test_sort.js` drives the record table's column
sorting in a real DOM, which is the only way to catch a comparator bug. Uses a temporary database and leaves no
trace.

## Layout notes

The score header, each score row, the totals line, and the read-only detail rows
all share one CSS grid template, so the three columns cannot drift apart. If you
change a column width, change it in the shared rule and everything follows.
