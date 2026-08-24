# Captain's Log

A solo game log for Star Trek: Captain's Chair. Photograph the scorepad, check
what it read, save. Or type it in by hand.

Built to sit on a Raspberry Pi on your LAN. Flask, SQLite, and one outbound API
call when you scan a sheet. No compiled dependencies beyond Pillow.

## What it records

Per game: date, your captain, board side, the bot's captain and rank, how the
game ended, the eight score rows for both sides, computed totals, and the photo
of the sheet if you scanned one.

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
export CC_SECRET_KEY="$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
export ANTHROPIC_API_KEY="sk-ant-..."
python3 app.py
```

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
    --bind 0.0.0.0:8080 app:app
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

Do not forward a port for this. On your LAN it is reachable at
`http://<pi>:8080`. If you later want it from outside, put Tailscale on the Pi
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

## Backups

Everything lives under `CC_DATA_DIR`: `captains_log.db` plus a `photos/`
folder. The database is in WAL mode, so copy it with sqlite rather than `cp`:

```bash
sqlite3 /var/lib/captains-log/captains_log.db ".backup /tmp/cc-backup.db"
tar czf cc-$(date +%F).tar.gz -C /var/lib/captains-log photos /tmp/cc-backup.db
```

## Captains

`db.py` seeds the eleven captains I could confirm across both boxes, grouped by
which box they came from.

The captain fields are dropdowns, not free text, so a typo cannot mint a phantom
captain that splits your stats later. To add one, pick "Add a captain" at the
bottom of the list and a name field appears alongside a box selector.

Matching is case-insensitive throughout. If a captain already exists under a
different capitalisation, that spelling wins, so "georgiou" resolves to
"Georgiou" rather than creating a second one. A scanned sheet that names an
unknown captain drops into the add field rather than being discarded.

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
python3 test_app.py && python3 test_stats.py
```

The first covers the scoring rules, the Burn path, negative values, validation,
auth, pagination, and the extraction parser. The second covers the stats
filters, the perspective toggle, and the aggregations, including the awkward
cases: a single data point, identical scores, and negative totals. Uses a temporary database and leaves no
trace.

## Layout notes

The score header, each score row, the totals line, and the read-only detail rows
all share one CSS grid template, so the three columns cannot drift apart. If you
change a column width, change it in the shared rule and everything follows.
